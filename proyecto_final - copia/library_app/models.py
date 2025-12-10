from django.db import models
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from datetime import datetime

class User(models.Model):
    """Usuarios de la biblioteca"""
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    
    #Complemento
    favorite_authors = models.TextField(blank=True, help_text="Autores favoritos separados por comas")
    favorite_genres = models.TextField(blank=True, help_text="Géneros favoritos separados por comas")
    
    class Meta:
        db_table = 'library_users'
        ordering = ['username']
    
    def __str__(self):
        return f"{self.username} - {self.full_name}"


class Book(models.Model):
    """Libros de la biblioteca - Tabla particionada por año"""
    # Campos del CSV
    book_id = models.IntegerField()  # Ya NO es unique aquí
    title = models.CharField(max_length=500)
    authors = models.CharField(max_length=500)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True)
    isbn = models.CharField(max_length=13, null=True, blank=True)
    isbn13 = models.CharField(max_length=13, null=True, blank=True)
    language_code = models.CharField(max_length=10, default='eng')
    num_pages = models.IntegerField(null=True, blank=True)
    ratings_count = models.IntegerField(default=0)
    text_reviews_count = models.IntegerField(default=0)
    publication_date = models.DateField(null=True, blank=True)
    publication_year = models.IntegerField(null=True, blank=True, db_index=True)  # Para particionamiento
    
    publisher = models.CharField(max_length=300, null=True, blank=True)
    
    # Campo para Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)
    is_available = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'library_books'
        indexes = [
            GinIndex(fields=['search_vector'], name='books_search_idx'),
            models.Index(fields=['publication_year'], name='books_year_idx'),
            models.Index(fields=['authors'], name='books_authors_idx'),
        ]
        ordering = ['-average_rating']
    
    def save(self, *args, **kwargs):
        # Auto-calcular año de publicación
        if self.publication_date and not self.publication_year:
            self.publication_year = self.publication_date.year
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.title} - {self.authors}"


class Loan(models.Model):
    """Préstamos de libros - Relaciona usuarios con libros"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loans')
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='loans')
    
    borrowed_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True)
    returned_date = models.DateTimeField(null=True, blank=True)
    is_returned = models.BooleanField(default=False)
    
    # Rating del usuario para este libro (para recomendaciones)
    user_rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    
    class Meta:
        db_table = 'library_loans'
        ordering = ['-borrowed_date']
        indexes = [
            models.Index(fields=['user', 'is_returned']),
            models.Index(fields=['book', 'is_returned']),
            models.Index(fields=['borrowed_date']),
        ]
        unique_together = ['user', 'book', 'borrowed_date']
    
    def __str__(self):
        status = "Devuelto" if self.is_returned else "Prestado"
        return f"{self.user.username} - {self.book.title} ({status})"

#Complemento
class UserPreference(models.Model):
    """Preferencias detalladas de usuarios para recomendaciones"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preferences')
    
    preferred_authors = models.TextField(blank=True)  
    preferred_page_range = models.CharField(max_length=50, blank=True)  
    min_rating_preference = models.DecimalField(max_digits=2, decimal_places=1, default=3.5)
    
    # Estadísticas
    total_books_read = models.IntegerField(default=0)
    average_user_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'library_user_preferences'
    
    def __str__(self):
        return f"Preferencias de {self.user.username}"