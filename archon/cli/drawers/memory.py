from __future__ import annotations

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, PlaceholderCommand

DRAWER_ID = "memory"
COMMAND_IDS = ("memory.search", "memory.export")


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
        store = self.bindings.MemoryStore()
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


class _Export(PlaceholderCommand):
    command_id = COMMAND_IDS[1]


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("search")
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

    @group.command("export")
    def export_command() -> None:
        _Export(bindings).invoke()

    return group
