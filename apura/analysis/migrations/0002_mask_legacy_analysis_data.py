"""Remove PII reconhecível de resultados persistidos antes desta correção."""

import re
from urllib.parse import unquote

from django.db import migrations


# Regras congeladas nesta migração para que ela não dependa de versões futuras
# do código da aplicação.
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?[\s-]?9?\s?\d{4}[-\s]?\d{4}(?!\d)")


def mask(text):
    text = EMAIL_RE.sub("[e-mail removido]", text)
    text = CPF_RE.sub("[CPF removido]", text)
    return PHONE_RE.sub("[telefone removido]", text)


def url_contains_pii(url):
    decoded = url
    for _ in range(4):
        if mask(decoded) != decoded:
            return True
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    return False


def sanitize(value, field=""):
    if isinstance(value, dict):
        return {key: sanitize(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, field) for item in value]
    if isinstance(value, str):
        if field == "url" and url_contains_pii(value):
            return ""
        return mask(value)
    return value


def mask_existing_analyses(apps, schema_editor):
    Analysis = apps.get_model("analysis", "Analysis")
    database = schema_editor.connection.alias
    last_id = None
    while True:
        query = Analysis.objects.using(database).only("id", "claim_summary", "technical").order_by("id")
        if last_id is not None:
            query = query.filter(id__gt=last_id)
        batch = list(query[:500])
        if not batch:
            break
        last_id = batch[-1].id
        changed = []
        for analysis in batch:
            claim_summary = mask(analysis.claim_summary)
            technical = sanitize(analysis.technical)
            if claim_summary != analysis.claim_summary or technical != analysis.technical:
                analysis.claim_summary = claim_summary
                analysis.technical = technical
                changed.append(analysis)
        if changed:
            Analysis.objects.using(database).bulk_update(changed, ["claim_summary", "technical"])


class Migration(migrations.Migration):
    dependencies = [("analysis", "0001_initial")]

    operations = [migrations.RunPython(mask_existing_analyses, migrations.RunPython.noop)]
