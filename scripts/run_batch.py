"""Run full batch analysis — standalone single-threaded script."""
import os
import psycopg2, time, sys
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""SELECT p.id FROM parcels p
        JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE sa.is_subdividable = true
          AND p.geom_stateplane IS NOT NULL AND p.area_sqft > 0
        ORDER BY p.area_sqft ASC""")
    ids = [r[0] for r in cur.fetchall()]
    total = len(ids)
    print(f"Processing {total:,} parcels...", flush=True)

    from backend.analysis.batch_processor import _load_and_analyze, _store_result

    ok = no = err = 0
    t0 = time.time()

    for i, pid in enumerate(ids):
        t1 = time.time()
        try:
            result = _load_and_analyze(pid, conn)
            dt = time.time() - t1
            if dt > 30:
                err += 1
                continue
            _store_result(conn, result)
            if result.is_subdividable:
                ok += 1
            else:
                no += 1
            if (i + 1) % 500 == 0:
                conn.commit()
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate / 60
                print(
                    f"  [{i+1:,}/{total:,}] {rate:.1f}/sec ETA={eta:.1f}min "
                    f"ok={ok} no={no} err={err}",
                    flush=True,
                )
        except Exception:
            err += 1
            try:
                conn.rollback()
            except Exception:
                pass

    conn.commit()
    elapsed = time.time() - t0
    print(f"\nDone: {elapsed/60:.1f}min ({total/elapsed:.1f}/sec)", flush=True)
    print(f"ok={ok} no={no} err={err}", flush=True)

    cur = conn.cursor()
    cur.execute("""SELECT subdivision_type, COUNT(*), AVG(num_possible_lots)::numeric(5,1)
        FROM subdivision_analysis WHERE is_subdividable = true AND subdivision_type IS NOT NULL
        GROUP BY subdivision_type ORDER BY COUNT(*) DESC""")
    print("\n=== Results ===", flush=True)
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]:,} parcels, avg {row[2]} lots", flush=True)

    cur.execute("SELECT COUNT(*) FROM subdivision_analysis WHERE proposed_lots IS NOT NULL")
    print(f"Parcels with geometry: {cur.fetchone()[0]:,}", flush=True)
    conn.close()

if __name__ == "__main__":
    main()
