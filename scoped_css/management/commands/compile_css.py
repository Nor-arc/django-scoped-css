from django.core.management.base import BaseCommand, CommandError


def _stylesheets(ref):
    """The colocated stylesheets attached to a TemplateRef (or ``()`` for an unknown template)."""
    if ref is None:
        return ()
    sheets = getattr(ref, "stylesheets", None)
    if sheets is None:
        sheets = (getattr(ref, "css", None), getattr(ref, "module_css", None))
    return tuple(p for p in sheets if p)


class Command(BaseCommand):
    help = "Compile colocated stylesheets into per-entry scoped bundles + manifest.json."

    def add_arguments(self, parser):
        parser.add_argument("--app", action="append", dest="apps", default=None, metavar="LABEL")
        parser.add_argument("--check", action="store_true", help="Exit 1 if any bundle is stale or missing.")
        parser.add_argument("--list", action="store_true", help="Print the entry graphs and exit.")

    def handle(self, *args, **options):
        from scoped_css import discovery

        apps = self._select_apps(discovery, options.get("apps"))

        if options.get("list"):
            return self._list(discovery, apps)
        if options.get("check"):
            return self._check(discovery, apps)
        return self._build(apps)

    # ------------------------------------------------------------------ helpers

    def _select_apps(self, discovery, labels):
        participating = list(discovery.participating_apps())
        if not labels:
            return participating
        by_label = {app.label: app for app in participating}
        selected = []
        for label in labels:
            if label not in by_label:
                raise CommandError(
                    f"--app {label}: not a participating app (known: {', '.join(sorted(by_label)) or 'none'})"
                )
            selected.append(by_label[label])
        return selected

    # ------------------------------------------------------------------- modes

    def _build(self, apps):
        from scoped_css.build import build_app

        total = 0
        for app in apps:
            records = build_app(app) or []
            total += len(records)
            for record in records:
                self.stdout.write(f"{app.label}: {record.entry} -> {record.bundle} ({len(record.sources)} source(s))")
                for warning in getattr(record, "warnings", ()) or ():
                    self.stdout.write(self.style.WARNING(f"  ! {warning}"))
        self.stdout.write(self.style.SUCCESS(f"scoped_css: {total} bundle(s) across {len(apps)} app(s)."))

    def _list(self, discovery, apps):
        """One block per entry; its sources indented beneath it with their scope kind and files.

        The scope attribute is printed once on the entry line (it is the page scope, shared by
        every ``page``-kind source); only an ``element``-kind source, which compiles under its own
        attribute, repeats one. Columns are aligned per block so the files line up.
        """
        from scoped_css import graph

        for app in apps:
            app_templates = discovery.scan(app)
            count = len(app_templates.entries)
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"{app.label} ({count} {'entry' if count == 1 else 'entries'})")
            )
            for entry in app_templates.entries:
                entry_graph = graph.build_entry_graph(app_templates, entry)
                self.stdout.write(f"  entry {entry}  [{entry_graph.attr}]")

                rows = []
                for source in entry_graph.ordered_sources:
                    name, attr, kind = source[0], source[1], source[2]
                    sheets = ", ".join(p.name for p in _stylesheets(app_templates.templates.get(name))) or "-"
                    scope = kind if attr == entry_graph.attr else f"{kind} [{attr}]"
                    rows.append((name, scope, sheets))

                name_width = max((len(r[0]) for r in rows), default=0)
                scope_width = max((len(r[1]) for r in rows), default=0)
                for name, scope, sheets in rows:
                    self.stdout.write(f"      {name:<{name_width}}  {scope:<{scope_width}}  {sheets}")

                for name in entry_graph.external:
                    self.stdout.write(f"      {name}  (outside the app: edge only)")
                for warning in entry_graph.warnings or []:
                    self.stdout.write(self.style.WARNING(f"    ! {warning}"))
                self.stdout.write("")

    def _check(self, discovery, apps):
        from scoped_css import dev, graph, manifest

        stale = []
        for app in apps:
            app_templates = discovery.scan(app)
            for entry in app_templates.entries:
                entry_graph = graph.build_entry_graph(app_templates, entry)
                # An entry whose closure has no stylesheets produces no bundle; not having one is correct.
                if not any(
                    _stylesheets(app_templates.templates.get(source[0])) for source in entry_graph.ordered_sources
                ):
                    continue
                record = manifest.lookup(entry)
                if dev.is_stale(record, app_templates.output_dir):
                    stale.append(f"{app.label}: {entry} ({'no bundle' if not record else 'stale'})")

        if stale:
            raise CommandError("scoped_css: bundles are missing or out of date:\n  " + "\n  ".join(stale))
        self.stdout.write(self.style.SUCCESS("scoped_css: all bundles are up to date."))
