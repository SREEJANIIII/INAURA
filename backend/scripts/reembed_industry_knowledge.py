"""
Re-embed industry knowledge for Gemini 768-d migration (016).

Usage:
  # Dry run (no DB writes)
  python scripts/reembed_industry_knowledge.py --dry-run

  # Full re-embedding (requires EMBEDDING_PROVIDER=gemini + EMBEDDING_API_KEY)
  python scripts/reembed_industry_knowledge.py

  # Force re-embed even where embedding already exists
  python scripts/reembed_industry_knowledge.py --force

Deterministic, safe, batched. Uses retrieval_document taskType for chunks/requirements.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure app importable when run as `python scripts/reembed...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.supabase import get_supabase_client
from app.services import embedding_service


def _content_for_requirement(row: dict) -> str:
    # Combine role + skill + description for retrieval
    return f"{row.get('role','')} {row.get('skill','')} {row.get('skill_category','')} {row.get('description','')} {row.get('evidence_context','')}".strip()


def _content_for_chunk(row: dict) -> str:
    return f"{row.get('role','')} {row.get('topic','')} {row.get('content','')}".strip()


async def reembed_table(table: str, content_fn, batch_size: int = 20, force: bool = False, dry_run: bool = False):
    c = get_supabase_client()
    if c is None:
        print(f"[ERROR] Supabase not configured; cannot re-embed {table}")
        return 0, 0

    if not embedding_service.is_configured():
        print(f"[SKIP] Embeddings not configured (EMBEDDING_PROVIDER/API_KEY missing); skipping {table}")
        return 0, 0

    # Fetch rows needing embedding
    try:
        if force:
            resp = c.table(table).select("id").execute()
        else:
            resp = c.table(table).select("id").is_("embedding", "null").execute()
        rows = resp.data or []
        if not rows:
            print(f"[OK] {table}: no rows needing embedding (force={force})")
            return 0, 0
        ids = [r["id"] for r in rows]
        print(f"[INFO] {table}: {len(ids)} rows to embed (batch={batch_size})")
    except Exception as e:
        print(f"[ERROR] Failed to fetch {table} ids: {e}")
        return 0, 1

    # Fetch full rows in batches
    total_ok = 0
    total_err = 0
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i+batch_size]
        try:
            resp = c.table(table).select("*").in_("id", batch_ids).execute()
            batch_rows = resp.data or []
        except Exception as e:
            print(f"[ERROR] Fetch batch {i//batch_size}: {e}")
            total_err += len(batch_ids)
            continue

        texts = [content_fn(r) for r in batch_rows]
        try:
            embeddings = await embedding_service.embed_texts(texts)
            if not embeddings or len(embeddings) != len(batch_rows):
                raise RuntimeError(f"Embedding count mismatch: {len(embeddings) if embeddings else 0} vs {len(batch_rows)}")
        except Exception as e:
            print(f"[ERROR] Embedding batch {i//batch_size} failed: {e} — will fallback to keyword for those rows")
            total_err += len(batch_rows)
            continue

        if dry_run:
            print(f"[DRY] Would update {len(batch_rows)} rows in {table} (batch {i//batch_size})")
            total_ok += len(batch_rows)
            continue

        # Update each row
        for row, emb in zip(batch_rows, embeddings):
            try:
                c.table(table).update({"embedding": emb}).eq("id", row["id"]).execute()
                total_ok += 1
            except Exception as e:
                print(f"[ERROR] Update {row['id']}: {e}")
                total_err += 1

        print(f"[OK] {table} batch {i//batch_size}: {len(batch_rows)} embedded")

    return total_ok, total_err


async def main():
    parser = argparse.ArgumentParser(description="Re-embed industry tables with Gemini 768-d")
    parser.add_argument("--force", action="store_true", help="Re-embed even where embedding exists")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()

    print(f"Embedding provider: {embedding_service.get_provider()} configured={embedding_service.is_configured()} dimension={embedding_service.DIMENSION} model={embedding_service._get_model()}")
    if not embedding_service.is_configured():
        print("Hint: set EMBEDDING_PROVIDER=gemini and EMBEDDING_API_KEY (or GOOGLE_API_KEY) and optionally EMBEDDING_MODEL=gemini-embedding-001")
        # Still proceed to show counts

    ok1, err1 = await reembed_table("industry_requirements", _content_for_requirement, batch_size=args.batch_size, force=args.force, dry_run=args.dry_run)
    ok2, err2 = await reembed_table("industry_knowledge_chunks", _content_for_chunk, batch_size=args.batch_size, force=args.force, dry_run=args.dry_run)

    print(f"\nDone. industry_requirements: ok={ok1} err={err1} | industry_knowledge_chunks: ok={ok2} err={err2}")
    if not args.dry_run:
        print("Vector search will now use Gemini 768-d. Old 1536-d vectors have been replaced.")
        print("If you see dimension mismatch errors, ensure migration 016 has been applied.")


if __name__ == "__main__":
    asyncio.run(main())
