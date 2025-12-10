import csv
from django.core.management.base import BaseCommand
from library_app.models import Book
from django.contrib.postgres.search import SearchVector

class Command(BaseCommand):
    help = 'Importa libros desde un archivo CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Ruta al archivo CSV')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        
        self.stdout.write('Importando libros...')
        
        with open(csv_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            count = 0
            
            for row in reader:
                try:
                    book, created = Book.objects.update_or_create(
                        book_id=int(row['bookID']),
                        defaults={
                            'title': row['title'],
                            'authors': row['authors'],
                            'average_rating': float(row['average_rating']) if row['average_rating'] else None,
                            'isbn': row.get('isbn', ''),
                            'isbn13': row.get('isbn13', ''),
                            'language_code': row.get('language_code', 'eng'),
                            'num_pages': int(row['num_pages']) if row['num_pages'] else None,
                            'ratings_count': int(row['ratings_count']) if row['ratings_count'] else 0,
                            'text_reviews_count': int(row['text_reviews_count']) if row['text_reviews_count'] else 0,
                            'publication_date': row.get('publication_date', ''),
                            'publisher': row.get('publisher', ''),
                        }
                    )
                    count += 1
                    if count % 100 == 0:
                        self.stdout.write(f'Procesados {count} libros...')
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error en línea {count}: {e}'))
        
        self.stdout.write(self.style.SUCCESS(f'✅ {count} libros importados correctamente'))
        
        # Actualizar search_vector para todos los libros
        self.stdout.write('Actualizando índices de búsqueda...')
        Book.objects.update(
            search_vector=SearchVector('title', 'authors', 'publisher', config='english')
        )
        self.stdout.write(self.style.SUCCESS('✅ Índices actualizados'))