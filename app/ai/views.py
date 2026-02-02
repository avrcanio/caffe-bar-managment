import re

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from artikli.models import Artikl


def _extract_query(text: str) -> str:
    query = (text or "").strip()
    if not query:
        return ""
    query = query.replace("\u0111", "dj").replace("\u0110", "Dj")
    patterns = [
        r"^(pronadi|pronadji)\s+mi\s+artikl\s+",
        r"^(pronadi|pronadji)\s+artikl\s+",
        r"^(pronadi|pronadji)\s+mi\s+",
    ]
    for pattern in patterns:
        if re.match(pattern, query, flags=re.IGNORECASE):
            return re.sub(pattern, "", query, flags=re.IGNORECASE).strip()
    return query


@method_decorator(login_required, name="dispatch")
class AiSearchView(TemplateView):
    template_name = "ai/search.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        raw_query = (self.request.GET.get("q") or "").strip()
        query = _extract_query(raw_query)
        results = []
        if query:
            results = list(
                Artikl.objects.filter(name__icontains=query)
                .order_by("name")
                .prefetch_related("normativ__items__ingredient")[:50]
            )
        context.update(
            {
                "raw_query": raw_query,
                "query": query,
                "results": results,
                "result_count": len(results),
            }
        )
        return context
