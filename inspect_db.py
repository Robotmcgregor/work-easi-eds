#!/usr/bin/env python3
"""
Django-style database inspection tool for EDS
Similar to Django's 'python manage.py inspectdb'
"""

import sys
from pathlib import Path

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

def inspect_database():
    """Inspect database tables like Django's inspectdb command"""
    try:
        from src.database.connection import DatabaseManager
        import sqlalchemy
        
        print("🔍 EDS DATABASE INSPECTION")
        print("=" * 60)
        
        # Get database session
        db = DatabaseManager()
        engine = db.engine
        inspector = sqlalchemy.inspect(engine)
        
        # Get all table names
        table_names = inspector.get_table_names()
        
        for table_name in sorted(table_names):
            print(f"\n📋 TABLE: {table_name}")
            print("-" * 40)
            
            # Get columns for this table
            columns = inspector.get_columns(table_name)
            
            for col in columns:
                nullable = "NULL" if col.get('nullable', True) else "NOT NULL"
                default = f" DEFAULT {col.get('default', '')}" if col.get('default') else ""
                print(f"  {col['name']:<25} {str(col['type']):<20} {nullable}{default}")
            
            # Get indexes
            try:
                indexes = inspector.get_indexes(table_name)
                if indexes:
                    print("  Indexes:")
                    for idx in indexes:
                        unique = "UNIQUE " if idx.get('unique', False) else ""
                        columns_str = ", ".join(idx['column_names'])
                        print(f"    {unique}{idx['name']}: ({columns_str})")
            except:
                pass
                
            # Get foreign keys
            try:
                fks = inspector.get_foreign_keys(table_name)
                if fks:
                    print("  Foreign Keys:")
                    for fk in fks:
                        local_cols = ", ".join(fk['constrained_columns'])
                        ref_table = fk['referred_table']
                        ref_cols = ", ".join(fk['referred_columns'])
                        print(f"    {local_cols} -> {ref_table}({ref_cols})")
            except:
                pass
        
        print(f"\n✅ Database inspection complete!")
        print(f"Found {len(table_names)} tables")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def show_model_attributes():
    """Show model attributes like Django models"""
    try:
        from src.database.models import LandsatTile
        from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
        from src.database.qc_models import QCValidation
        
        models = [
            ("LandsatTile", LandsatTile),
            ("NVMSDetection", NVMSDetection), 
            ("NVMSResult", NVMSResult),
            ("NVMSRun", NVMSRun),
            ("QCValidation", QCValidation)
        ]
        
        print("\n🏗️  MODEL ATTRIBUTES")
        print("=" * 60)
        
        for model_name, model_class in models:
            print(f"\n📊 {model_name}")
            print("-" * 30)
            
            # Get all column attributes
            for column_name in model_class.__table__.columns.keys():
                column = model_class.__table__.columns[column_name]
                print(f"  {column_name:<25} {str(column.type):<20}")
        
    except Exception as e:
        print(f"❌ Model inspection error: {e}")

if __name__ == "__main__":
    inspect_database()
    show_model_attributes()