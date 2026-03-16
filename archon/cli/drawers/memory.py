from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand
from archon.cli.copy import DRAWER_COPY
from archon.memory.store import MemoryStore

DRAWER_ID = "memory"
COMMAND_IDS = ("memory.search", "memory.export", "memory.import")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


class _Search(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        query: str,
        tenant_id: str,
        top_k: int,
        config_path: str,
    ):
        session.run_step(0, self.bindings._load_config, config_path)
        store = MemoryStore()
        try:
            results = session.run_step(
                1,
                store.search,
                query=query,
                tenant_id=tenant_id,
                top_k=top_k,
            )
        finally:
            store.close()
        lines = []
        for row in results:
            lines.append(
                " ".join(
                    [
                        row.memory.memory_id,
                        f"{row.similarity:.3f}",
                        row.memory.role,
                        str(row.memory.content)[:70],
                    ]
                )
            )
        session.run_step(2, lambda: None)
        if lines:
            session.print(renderer.detail_panel(self.command_id, lines))
            return {"result_count": len(lines), "tenant_id": tenant_id}
        return {
            "result_key": "empty",
            "result_count": 0,
            "tenant_id": tenant_id,
        }


class _Export(ArchonCommand):
    command_id = COMMAND_IDS[1]

    def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        tenant_id: str,
        output_path: str | None,
        include_forgotten: bool,
        limit: int | None,
        config_path: str,
    ):
        session.run_step(0, self.bindings._load_config, config_path)
        store = MemoryStore()
        try:
            resolved = output_path
            if not resolved:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                resolved = f"archon-memory-{tenant_id}-{stamp}.jsonl"
            resolved_path = str(Path(resolved))
            exported = session.run_step(
                1,
                store.export_tenant,
                tenant_id=str(tenant_id),
                output_path=resolved_path,
                include_forgotten=bool(include_forgotten),
                limit=limit,
            )
        finally:
            store.close()
        session.run_step(2, lambda: None)
        session.print(
            renderer.detail_panel(
                self.command_id,
                [f"output={resolved_path}", f"rows={int(exported)}"],
            )
        )
        return {
            "tenant_id": tenant_id,
            "output_path": resolved_path,
            "row_count": int(exported),
        }


class _Import(ArchonCommand):
    command_id = COMMAND_IDS[2]

    def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        tenant_id: str,
        input_path: str,
        allow_tenant_mismatch: bool,
        on_conflict: str,
        limit: int | None,
        config_path: str,
    ):
        session.run_step(0, self.bindings._load_config, config_path)
        store = MemoryStore()
        try:
            result = session.run_step(
                1,
                store.import_tenant,
                tenant_id=str(tenant_id),
                input_path=str(input_path),
                allow_tenant_mismatch=bool(allow_tenant_mismatch),
                on_conflict=str(on_conflict),
                limit=limit,
            )
        finally:
            store.close()
        session.run_step(2, lambda: None)
        session.print(
            renderer.detail_panel(
                self.command_id,
                [
                    f"input={input_path}",
                    f"imported={int(result.get('imported', 0))}",
                    f"replaced={int(result.get('replaced', 0))}",
                    f"skipped={int(result.get('skipped', 0))}",
                ],
            )
        )
        return {
            "tenant_id": tenant_id,
            "imported": int(result.get("imported", 0)),
            "replaced": int(result.get("replaced", 0)),
            "skipped": int(result.get("skipped", 0)),
        }


def build_group(bindings):
    @click.group(
        name=DRAWER_ID,
        invoke_without_command=True,
        help=str(DRAWER_META["tagline"]),
    )
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("search", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.argument("query")
    @click.option("--tenant", "tenant_id", default="default")
    @click.option("--top-k", default=10, type=int)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def search_command(
        query: str,
        tenant_id: str,
        top_k: int,
        config_path: str,
    ) -> None:
        _Search(bindings).invoke(
            query=query,
            tenant_id=tenant_id,
            top_k=top_k,
            config_path=config_path,
        )

    @group.command("export", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.option("--tenant", "tenant_id", default="default")
    @click.option("--out", "output_path", default=None)
    @click.option("--include-forgotten", is_flag=True, default=False)
    @click.option("--limit", type=int, default=None)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def export_command(
        tenant_id: str,
        output_path: str | None,
        include_forgotten: bool,
        limit: int | None,
        config_path: str,
    ) -> None:
        _Export(bindings).invoke(
            tenant_id=tenant_id,
            output_path=output_path,
            include_forgotten=include_forgotten,
            limit=limit,
            config_path=config_path,
        )

    @group.command("import", help=str(COMMAND_HELP[COMMAND_IDS[2]]))
    @click.option("--tenant", "tenant_id", default="default")
    @click.option("--in", "input_path", required=True)
    @click.option("--allow-tenant-mismatch", is_flag=True, default=False)
    @click.option(
        "--on-conflict",
        type=click.Choice(["skip", "overwrite"], case_sensitive=False),
        default="skip",
        show_default=True,
    )
    @click.option("--limit", type=int, default=None)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def import_command(
        tenant_id: str,
        input_path: str,
        allow_tenant_mismatch: bool,
        on_conflict: str,
        limit: int | None,
        config_path: str,
    ) -> None:
        _Import(bindings).invoke(
            tenant_id=tenant_id,
            input_path=input_path,
            allow_tenant_mismatch=allow_tenant_mismatch,
            on_conflict=on_conflict.lower(),
            limit=limit,
            config_path=config_path,
        )

    return group
