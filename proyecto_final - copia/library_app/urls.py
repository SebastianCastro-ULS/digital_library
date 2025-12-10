from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('recommendations/<str:username>/', views.user_recommendations, name='recommendations'),
    #path('recommendations/', views.recommendations, name='recommendations'),
    path('borrow/<int:book_id>/', views.borrow_book, name='borrow_book'),
    path('return/<int:book_id>/', views.return_book, name='return_book'),
    path('borrowed/', views.borrowed_books, name='borrowed_books'),
    path('user/<str:username>/', views.user_dashboard, name='user_dashboard'),
    path('user/<str:username>/recommendations/', views.user_recommendations, name='user_recommendations'),
    path('year/<int:year>/', views.books_by_year, name='books_by_year'),
    path('years/', views.years_list, name='years_list'),
]