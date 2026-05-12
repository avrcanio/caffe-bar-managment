import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.generic import TemplateView, View


DOWNLOAD_ROOT = settings.BASE_DIR / "download"
CONTENT_TYPES = {
    ".appinstaller": "application/appinstaller",
    ".msix": "application/msix",
    ".msixbundle": "application/msixbundle",
    ".cer": "application/pkix-cert",
    ".ps1": "text/plain; charset=utf-8",
    ".msi": "application/x-msi",
    ".zip": "application/zip",
}
NO_STORE_SUFFIXES = {".appinstaller", ".msixbundle", ".cer", ".ps1"}
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def _iter_file_range(file_obj, start: int, length: int, chunk_size: int = 8192):
    file_obj.seek(start)
    remaining = length
    while remaining > 0:
        chunk = file_obj.read(min(chunk_size, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        yield chunk


class DownloadIndexView(TemplateView):
    template_name = "download/index.html"


class DownloadFileView(View):
    def get(self, request, path: str):
        full_path = safe_join(str(DOWNLOAD_ROOT), path)
        if not full_path:
            raise Http404("File not found.")

        file_path = Path(full_path)
        if not file_path.is_file():
            raise Http404("File not found.")

        suffix = file_path.suffix.lower()
        content_type = CONTENT_TYPES.get(suffix, "application/octet-stream")
        file_size = file_path.stat().st_size
        range_header = request.headers.get("Range", "").strip()

        if range_header:
            match = RANGE_RE.match(range_header)
            if match:
                start_str, end_str = match.groups()
                if start_str:
                    start = int(start_str)
                    end = int(end_str) if end_str else file_size - 1
                else:
                    length = int(end_str)
                    start = max(file_size - length, 0)
                    end = file_size - 1

                start = min(start, file_size - 1)
                end = min(end, file_size - 1)
                if start <= end:
                    length = end - start + 1
                    response = StreamingHttpResponse(
                        _iter_file_range(file_path.open("rb"), start, length),
                        status=206,
                        content_type=content_type,
                    )
                    response["Content-Length"] = str(length)
                    response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
                else:
                    raise Http404("Invalid range.")
            else:
                raise Http404("Invalid range.")
        else:
            response = FileResponse(file_path.open("rb"), content_type=content_type)
            response["Content-Length"] = str(file_size)

        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = f'inline; filename="{file_path.name}"'
        response["X-Content-Type-Options"] = "nosniff"

        if suffix in NO_STORE_SUFFIXES:
            response["Cache-Control"] = "no-store, no-cache, must-revalidate"
        elif suffix in {".msix", ".msi", ".zip"}:
            response["Cache-Control"] = "public, max-age=31536000, immutable"

        return response
