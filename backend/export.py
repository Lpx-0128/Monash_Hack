import json
import argparse
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models
from . import crud

def export_cases(output_path: str, run_kind: str = None):
    db: Session = SessionLocal()
    try:
        query = db.query(models.CaseModel)
        cases = query.all()
        
        exported_cases = []
        for c in cases:
            schema_case = crud.map_db_to_schema(c)
            # Filter by run kind if specified
            if run_kind and schema_case.run.kind.value != run_kind:
                continue
                
            # Convert to dict and handle aliases properly (like "from")
            case_dict = schema_case.model_dump(mode='json', by_alias=True)
            exported_cases.append(case_dict)
            
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(exported_cases, f, indent=2)
            
        print(f"Exported {len(exported_cases)} cases to {output_path}")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export cases to JSON")
    parser.add_argument("--output", type=str, default="submission.json", help="Output file path")
    parser.add_argument("--run-kind", type=str, choices=["DEMO", "EVAL"], help="Filter by run kind")
    args = parser.parse_args()
    
    export_cases(args.output, args.run_kind)
