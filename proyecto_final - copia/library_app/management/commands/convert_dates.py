from django.core.management.base import BaseCommand
from django.db import connection
from datetime import datetime

class Command(BaseCommand):
    help = 'Convierte publication_date de VARCHAR a DATE'

    def handle(self, *args, **options):
        self.stdout.write('Convirtiendo fechas...')
        
        with connection.cursor() as cursor:
            # 1. Agregar columna temporal para la fecha convertida
            self.stdout.write('Agregando columna temporal...')
            try:
                cursor.execute("""
                    ALTER TABLE library_app_book 
                    ADD COLUMN IF NOT EXISTS publication_date_temp DATE;
                """)
            except Exception as e:
                self.stdout.write(f'Columna ya existe: {e}')
            
            # 2. Convertir fechas de formato "9/16/2006" a DATE
            self.stdout.write('Convirtiendo formatos de fecha...')
            cursor.execute("""
                UPDATE library_app_book
                SET publication_date_temp = 
                    CASE 
                        WHEN publication_date IS NOT NULL AND publication_date != '' THEN
                            TO_DATE(publication_date, 'MM/DD/YYYY')
                        ELSE NULL
                    END
                WHERE publication_date_temp IS NULL;
            """)
            
            rows_updated = cursor.rowcount
            self.stdout.write(f'✅ {rows_updated} fechas convertidas')
            
            # 3. Agregar columna publication_year
            self.stdout.write('Agregando columna publication_year...')
            try:
                cursor.execute("""
                    ALTER TABLE library_app_book 
                    ADD COLUMN IF NOT EXISTS publication_year INTEGER;
                """)
            except Exception as e:
                self.stdout.write(f'Columna ya existe: {e}')
            
            # 4. Calcular año de publicación
            cursor.execute("""
                UPDATE library_app_book
                SET publication_year = EXTRACT(YEAR FROM publication_date_temp)
                WHERE publication_date_temp IS NOT NULL AND publication_year IS NULL;
            """)
            
            self.stdout.write(f'✅ Años calculados')
            
            # 5. Crear índice en publication_year
            self.stdout.write('Creando índice en publication_year...')
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_publication_year 
                    ON library_app_book(publication_year);
                """)
                self.stdout.write('✅ Índice creado')
            except Exception as e:
                self.stdout.write(f'Índice ya existe: {e}')
        
        self.stdout.write(self.style.SUCCESS('✅ Conversión completada'))
        self.stdout.write('NOTA: Debes renombrar publication_date_temp a publication_date manualmente en la próxima migración')