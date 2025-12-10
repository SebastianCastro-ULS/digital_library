from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from django.utils import timezone
from django.db.models import Q, Count, Case, When, Value, IntegerField, Avg, Sum
from django.db import models
from decimal import Decimal
from .models import Book, Loan, User


def home(request):
    """Página principal con búsqueda y filtros avanzados"""
    query = request.GET.get('q', '')
    selected_publisher = request.GET.get('publisher', '')
    min_rating = request.GET.get('min_rating', '')
    availability = request.GET.get('availability', '')
    pages = request.GET.get('pages', '')
    
    # Detectar si hay filtros activos
    filters_active = any([selected_publisher, min_rating, availability, pages])
    
    # Query base
    books = Book.objects.all()
    
    # Búsqueda por texto
    if query:
        search_query = SearchQuery(query, config='english')
        search_vector = SearchVector('title', 'authors', 'publisher', config='english')
        
        books = books.annotate(
            rank=SearchRank(search_vector, search_query)
        ).filter(rank__gte=0.01).order_by('-rank')
    
    # Filtro por editorial
    if selected_publisher:
        books = books.filter(publisher__iexact=selected_publisher)
    
    # Filtro por calificación mínima
    if min_rating:
        try:
            min_rating_decimal = Decimal(min_rating)
            books = books.filter(average_rating__gte=min_rating_decimal)
        except (ValueError, TypeError):
            pass
    
    # Filtro por disponibilidad
    if availability == 'available':
        books = books.filter(is_available=True)
    elif availability == 'borrowed':
        books = books.filter(is_available=False)
    
    # Filtro por páginas
    if pages == 'short':
        books = books.filter(num_pages__lt=200, num_pages__isnull=False)
    elif pages == 'medium':
        books = books.filter(num_pages__gte=200, num_pages__lte=400)
    elif pages == 'long':
        books = books.filter(num_pages__gt=400)
    
    # Si no hay búsqueda ni filtros, mostrar destacados
    if not query and not filters_active:
        books = books.filter(is_available=True).order_by('-average_rating')[:20]
    else:
        books = books[:50]
    
    # Obtener editoriales para el filtro (top 20 más comunes)
    publishers = Book.objects.exclude(
        publisher__isnull=True
    ).exclude(
        publisher=''
    ).values('publisher').annotate(
        count=Count('id')
    ).order_by('-count')[:20]
    
    context = {
        'books': books,
        'query': query,
        'publishers': publishers,
        'selected_publisher': selected_publisher,
        'min_rating': min_rating,
        'availability': availability,
        'pages': pages,
        'filters_active': filters_active,
    }
    return render(request, 'home.html', context)


def user_recommendations(request, username):
    """
    Sistema de recomendaciones inteligente que prioriza:
    1. Mismo autor Y misma editorial (peso 4)
    2. Solo mismo autor (peso 3)
    3. Solo misma editorial (peso 2)
    4. Mismo rango de calificación (peso 1)
    5. Libros populares (peso 0)
    """
    user = get_object_or_404(User, username=username)
    
    # Obtener TODOS los préstamos (incluye devueltos e históricos)
    user_loans = Loan.objects.filter(user=user).select_related('book')
    
    # Estadísticas para debug
    total_loans = user_loans.count()
    returned_loans = user_loans.filter(is_returned=True).count()
    active_loans = user_loans.filter(is_returned=False).count()
    
    # Si el usuario no tiene historial de préstamos
    if not user_loans.exists():
        books = Book.objects.filter(
            is_available=True
        ).order_by('-average_rating', '-ratings_count')[:20]
        
        debug_info = f'Sin historial | Mostrando: {books.count()} libros mejor valorados'
        
        return render(request, 'recommendations.html', {
            'title': f'Recomendaciones para {user.full_name}',
            'books': books,
            'user': user,
            'user_loans_exist': False,
            'debug_info': debug_info,
            'message': '¡Empieza tu aventura de lectura! Aquí los libros más populares.'
        })
    
    # Extraer IDs de libros ya leídos (para excluirlos)
    read_book_ids = list(user_loans.values_list('book_id', flat=True))
    
    # Extraer autores únicos de los libros leídos
    read_authors = set()
    for loan in user_loans:
        if loan.book.authors:
            # Separar por comas, limpiar espacios y agregar al set
            authors_list = [author.strip() for author in loan.book.authors.split(',')]
            read_authors.update(authors_list)
    
    # Extraer editoriales únicas
    read_publishers = set(
        user_loans.values_list('book__publisher', flat=True)
        .distinct()
        .exclude(book__publisher__isnull=True)
        .exclude(book__publisher='')
    )
    
    # Calcular calificación promedio de libros leídos (para recomendar similares)
    avg_rating = user_loans.aggregate(
        avg=Avg('book__average_rating')
    )['avg'] or Decimal('3.5')
    
    # Convertir a Decimal si no lo es
    if not isinstance(avg_rating, Decimal):
        avg_rating = Decimal(str(avg_rating))
    
    # Construir condiciones dinámicas para autores
    author_conditions = Q()
    for author in read_authors:
        # Búsqueda case-insensitive de coincidencia parcial
        author_conditions |= Q(authors__icontains=author)
    
    # Construir condiciones para editoriales
    publisher_conditions = Q()
    for publisher in read_publishers:
        publisher_conditions |= Q(publisher__iexact=publisher)
    
    # Query principal con sistema de pesos/prioridades
    recommendations = Book.objects.filter(
        is_available=True  # Solo libros disponibles
    ).exclude(
        book_id__in=read_book_ids  # Excluir ya leídos
    ).annotate(
        # Sistema de puntuación por prioridades
        priority_score=Case(
            # Peso 4: Mismo autor Y misma editorial
            When(
                author_conditions & publisher_conditions,
                then=Value(4)
            ),
            # Peso 3: Solo mismo autor
            When(author_conditions, then=Value(3)),
            
            # Peso 2: Solo misma editorial
            When(publisher_conditions, then=Value(2)),
            
            # Peso 1: Calificación similar (±0.5 puntos)
            When(
                Q(average_rating__gte=avg_rating - Decimal('0.5')) & 
                Q(average_rating__lte=avg_rating + Decimal('0.5')),
                then=Value(1)
            ),
            
            # Peso 0: Otros libros
            default=Value(0),
            output_field=IntegerField()
        ),
        # Popularidad como criterio secundario
        popularity=Count('loans')
    ).order_by(
        '-priority_score',      # 1° Prioridad calculada
        '-average_rating',      # 2° Mejor calificación
        '-popularity',          # 3° Más prestado
        '-publication_year'     # 4° Más reciente
    )
    
    # Verificar cuántas recomendaciones prioritarias hay ANTES del slice
    priority_count = recommendations.filter(priority_score__gte=2).count()
    
    # Tomar las top 30 recomendaciones
    top_recommendations = list(recommendations[:30])
    
    # Si hay pocas recomendaciones prioritarias, complementar con populares
    if priority_count < 10:
        priority_recs = list(recommendations.filter(priority_score__gte=2)[:15])
        priority_ids = [book.book_id for book in priority_recs]
        all_excluded = read_book_ids + priority_ids
        
        # Agregar libros populares bien valorados
        popular_books = Book.objects.filter(
            is_available=True,
            average_rating__gte=Decimal('4.0')  # Solo bien valorados
        ).exclude(
            book_id__in=all_excluded
        ).order_by('-ratings_count', '-average_rating')[:15]
        
        final_recommendations = priority_recs + list(popular_books)
    else:
        final_recommendations = top_recommendations
    
    # Información de debug mejorada
    debug_info = (
        f'Préstamos: {total_loans} (Activos: {active_loans}, Devueltos: {returned_loans}) | '
        f'Autores conocidos: {len(read_authors)} | '
        f'Editoriales: {len(read_publishers)} | '
        f'Recomendaciones prioritarias: {priority_count}'
    )
    
    # Información adicional para mostrar al usuario
    context_info = {
        'favorite_authors': ', '.join(list(read_authors)[:5]) if read_authors else 'Ninguno aún',
        'favorite_publishers': ', '.join(list(read_publishers)[:3]) if read_publishers else 'Ninguna aún',
        'avg_rating_preference': f'{avg_rating:.1f}',
        'total_books_read': total_loans
    }
    
    return render(request, 'recommendations.html', {
        'title': f'Recomendaciones personalizadas para {user.full_name}',
        'books': final_recommendations,
        'user': user,
        'user_loans_exist': True,
        'debug_info': debug_info,
        'context_info': context_info,
        'message': f'Basado en {total_loans} libro(s) que has leído'
    })
    

def borrow_book(request, book_id): 
    """Prestar un libro"""
    book = get_object_or_404(Book, book_id=book_id)
    
    if request.method == 'POST':
        if book.is_available:
            # Obtener o crear el usuario
            username = request.POST.get('username', '').strip()
            
            if not username:
                return render(request, 'borrow.html', {
                    'book': book,
                    'error': 'Por favor ingresa un nombre de usuario válido'
                })
            
            # Obtener o crear el usuario
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': f'{username}@example.com',
                    'full_name': username
                }
            )
            
            # Crear el préstamo
            Loan.objects.create(
                user=user,
                book=book,
                due_date=timezone.now() + timezone.timedelta(days=14)
            )
            
            # Marcar como no disponible
            book.is_available = False
            book.save()
            return redirect('home')
    
    return render(request, 'borrow.html', {'book': book})


def return_book(request, book_id):
    """Devolver un libro con opción de calificación"""
    book = get_object_or_404(Book, book_id=book_id)
    
    # Obtener el préstamo activo
    loan = Loan.objects.filter(book=book, is_returned=False).first()
    
    if not loan:
        return redirect('home')
    
    if request.method == 'POST':
        # Obtener la calificación si la proporciona
        rating = request.POST.get('rating')
        
        if rating:
            try:
                loan.user_rating = float(rating)
            except (ValueError, TypeError):
                pass
        
        # Marcar como devuelto
        loan.is_returned = True
        loan.returned_date = timezone.now()
        loan.save()
        
        # Marcar como disponible
        book.is_available = True
        book.save()
        
        return redirect('user_dashboard', username=loan.user.username)
    
    context = {'loan': loan}
    return render(request, 'return_book.html', context)


def borrowed_books(request):
    """Listado de libros prestados"""
    # Obtener todos los préstamos activos (no devueltos)
    loans = Loan.objects.filter(is_returned=False).order_by('-borrowed_date')
    
    return render(request, 'borrowed.html', {'loans': loans})


def user_dashboard(request, username):
    """Dashboard del usuario con sus préstamos y estadísticas avanzadas"""
    user = User.objects.filter(username=username).first()

    if not user:
        return render(request, 'user_not_found.html', {'username': username})

    # Préstamos activos
    current_loans = Loan.objects.filter(user=user, is_returned=False).order_by('-borrowed_date')

    # Historial de lectura (préstamos devueltos)
    reading_history = Loan.objects.filter(user=user, is_returned=True).select_related('book').order_by('-returned_date')

    # Filtro por calificación (opcional)
    rating_filter = request.GET.get('rating_filter')
    if rating_filter:
        try:
            min_rating = Decimal(rating_filter)
            reading_history = reading_history.filter(user_rating__gte=min_rating)
        except (ValueError, TypeError):
            pass

    # Total de libros leídos
    total_read = Loan.objects.filter(user=user, is_returned=True).count()

    # Calificación promedio del usuario
    average_user_rating = reading_history.aggregate(
        avg=Avg('user_rating')
    )['avg']

    # Autor más leído
    author_counts = {}
    for loan in Loan.objects.filter(user=user, is_returned=True).select_related('book'):
        if loan.book.authors:
            # Tomar solo el primer autor para simplificar
            author = loan.book.authors.split(',')[0].strip()
            author_counts[author] = author_counts.get(author, 0) + 1
    
    favorite_author = None
    favorite_author_count = 0
    if author_counts:
        favorite_author = max(author_counts, key=author_counts.get)
        favorite_author_count = author_counts[favorite_author]

    # Editorial favorita
    publisher_counts = {}
    for loan in Loan.objects.filter(user=user, is_returned=True).select_related('book'):
        if loan.book.publisher:
            publisher_counts[loan.book.publisher] = publisher_counts.get(loan.book.publisher, 0) + 1
    
    favorite_publisher = None
    favorite_publisher_count = 0
    if publisher_counts:
        favorite_publisher = max(publisher_counts, key=publisher_counts.get)
        favorite_publisher_count = publisher_counts[favorite_publisher]

    # Año más leído
    year_counts = {}
    for loan in Loan.objects.filter(user=user, is_returned=True).select_related('book'):
        if loan.book.publication_year:
            year = loan.book.publication_year
            year_counts[year] = year_counts.get(year, 0) + 1
    
    most_read_year = None
    most_read_year_count = 0
    if year_counts:
        most_read_year = max(year_counts, key=year_counts.get)
        most_read_year_count = year_counts[most_read_year]

    # Total de páginas leídas (aproximado)
    total_pages = Loan.objects.filter(
        user=user, 
        is_returned=True,
        book__num_pages__isnull=False
    ).aggregate(total=models.Sum('book__num_pages'))['total']

    context = {
        'user': user,
        'current_loans': current_loans,
        'reading_history': reading_history,
        'total_read': total_read,
        'average_user_rating': average_user_rating,
        'favorite_author': favorite_author,
        'favorite_author_count': favorite_author_count,
        'favorite_publisher': favorite_publisher,
        'favorite_publisher_count': favorite_publisher_count,
        'most_read_year': most_read_year,
        'most_read_year_count': most_read_year_count,
        'total_pages_read': total_pages,
    }

    return render(request, 'user_dashboard.html', context)


def books_by_year(request, year):
    """Mostrar libros publicados en un año específico"""
    try:
        year = int(year)
    except (ValueError, TypeError):
        return redirect('home')

    books = Book.objects.filter(publication_year=year).order_by('-average_rating', 'title')

    context = {
        'books': books,
        'year': year,
        'count': books.count(),
    }

    return render(request, 'books_by_year.html', context)


def years_list(request):
    """Mostrar lista de años disponibles en la biblioteca"""
    years = Book.objects.filter(
        publication_year__isnull=False
    ).values('publication_year').annotate(
        total=Count('id')
    ).order_by('-publication_year')

    context = {
        'years': years,
    }

    return render(request, 'years_list.html', context)


# FUNCIÓN AUXILIAR EXTRA: Para obtener recomendaciones categorizadas
def get_categorized_recommendations(username, limit_per_category=10):
    """
    Función auxiliar que devuelve recomendaciones organizadas por categoría.
    Útil para mostrar en diferentes secciones de la UI o para APIs.
    
    Returns:
        dict: {
            'same_author_and_publisher': [...],
            'same_author': [...],
            'same_publisher': [...],
            'similar_rating': [...],
            'metadata': {...}
        }
    """
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return {'error': 'Usuario no encontrado'}
    
    user_loans = Loan.objects.filter(user=user).select_related('book')
    
    if not user_loans.exists():
        return {'error': 'Usuario sin historial de préstamos'}
    
    # IDs de libros ya leídos
    read_book_ids = list(user_loans.values_list('book_id', flat=True))
    
    # Extraer autores
    read_authors = set()
    for loan in user_loans:
        if loan.book.authors:
            authors_list = [a.strip() for a in loan.book.authors.split(',')]
            read_authors.update(authors_list)
    
    # Extraer editoriales
    read_publishers = set(
        user_loans.values_list('book__publisher', flat=True)
        .distinct()
        .exclude(book__publisher__isnull=True)
        .exclude(book__publisher='')
    )
    
    # Calificación promedio
    avg_rating = user_loans.aggregate(avg=Avg('book__average_rating'))['avg'] or Decimal('3.5')
    if not isinstance(avg_rating, Decimal):
        avg_rating = Decimal(str(avg_rating))
    
    # Construir queries
    author_q = Q()
    for author in read_authors:
        author_q |= Q(authors__icontains=author)
    
    publisher_q = Q()
    for publisher in read_publishers:
        publisher_q |= Q(publisher__iexact=publisher)
    
    # Base queryset
    base_qs = Book.objects.filter(
        is_available=True
    ).exclude(book_id__in=read_book_ids)
    
    # Categorizar recomendaciones
    recommendations = {
        'same_author_and_publisher': list(
            base_qs.filter(author_q & publisher_q)
            .order_by('-average_rating')[:limit_per_category]
        ),
        'same_author': list(
            base_qs.filter(author_q)
            .exclude(id__in=base_qs.filter(author_q & publisher_q).values_list('id', flat=True))
            .order_by('-average_rating')[:limit_per_category]
        ),
        'same_publisher': list(
            base_qs.filter(publisher_q)
            .exclude(id__in=base_qs.filter(author_q).values_list('id', flat=True))
            .order_by('-average_rating')[:limit_per_category]
        ),
        'similar_rating': list(
            base_qs.filter(
                average_rating__gte=avg_rating - Decimal('0.5'),
                average_rating__lte=avg_rating + Decimal('0.5')
            ).exclude(
                id__in=base_qs.filter(author_q | publisher_q).values_list('id', flat=True)
            ).order_by('-ratings_count')[:limit_per_category]
        ),
        'metadata': {
            'favorite_authors': list(read_authors),
            'favorite_publishers': list(read_publishers),
            'avg_rating': float(avg_rating),
            'total_books_read': len(read_book_ids)
        }
    }
    
    return recommendations