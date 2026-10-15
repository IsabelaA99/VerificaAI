"""Repara cópias de metadados afetadas pelo mascaramento amplo da migração 0002."""

from django.db import migrations


REMOVAL_MARKERS = ("[e-mail removido]", "[CPF removido]", "[telefone removido]")
METADATA_FIELDS = (
    ("classification", "model_version", "model_version"),
    ("classification", "model_sha256", "model_sha256"),
    ("rules", "version", "rules_version"),
    ("calibrator", "version", "calibrator_version"),
)


def restore_technical_metadata(apps, schema_editor):
    Analysis = apps.get_model("analysis", "Analysis")
    database = schema_editor.connection.alias
    last_id = None
    while True:
        query = Analysis.objects.using(database).only(
            "id", "technical", "model_version", "model_sha256", "rules_version", "calibrator_version",
        ).order_by("id")
        if last_id is not None:
            query = query.filter(id__gt=last_id)
        batch = list(query[:500])
        if not batch:
            break
        last_id = batch[-1].id
        changed = []
        for analysis in batch:
            if not isinstance(analysis.technical, dict):
                continue
            repaired = False
            for group, key, column in METADATA_FIELDS:
                metadata = analysis.technical.get(group)
                if not isinstance(metadata, dict):
                    continue
                value = metadata.get(key)
                original = getattr(analysis, column)
                if isinstance(value, str) and any(marker in value for marker in REMOVAL_MARKERS) and value != original:
                    metadata[key] = original
                    repaired = True
            if repaired:
                changed.append(analysis)
        if changed:
            Analysis.objects.using(database).bulk_update(changed, ["technical"])


class Migration(migrations.Migration):
    dependencies = [("analysis", "0002_mask_legacy_analysis_data")]

    operations = [migrations.RunPython(restore_technical_metadata, migrations.RunPython.noop)]
