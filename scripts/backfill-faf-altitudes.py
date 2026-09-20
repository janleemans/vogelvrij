"""Populate closest-reference-point altitudes for already linked movements.

Run after migration 004. This is idempotent and preserves observations.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from vogelvrij.database import make_engine
from vogelvrij.models import FlightMovement
from vogelvrij.movements import update_faf_altitude


def main() -> None:
    engine = make_engine()
    last_id = 0
    updated = 0
    try:
        with Session(engine) as session:
            while True:
                movements = session.scalars(
                    select(FlightMovement)
                    .where(FlightMovement.id > last_id)
                    .order_by(FlightMovement.id)
                    .limit(100)
                    .options(selectinload(FlightMovement.observations))
                ).all()
                if not movements:
                    break
                for movement in movements:
                    changed = False
                    for observation in movement.observations:
                        changed = update_faf_altitude(movement, observation) or changed
                    if changed:
                        updated += 1
                last_id = movements[-1].id
                session.commit()
        print(f"Updated {updated} movement(s).")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
