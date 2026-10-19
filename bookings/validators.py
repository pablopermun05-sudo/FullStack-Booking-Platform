import zipfile
from pathlib import PurePath

from django.core.exceptions import ValidationError


MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".docx",
    ".xlsx",
    ".pptx",
    ".txt",
    ".csv",
}

OFFICE_CONTENT_TYPES = {
    ".docx": ("word/", "wordprocessingml"),
    ".xlsx": ("xl/", "spreadsheetml"),
    ".pptx": ("ppt/", "presentationml"),
}


def validate_booking_attachment(uploaded_file):
    filename = PurePath(uploaded_file.name).name
    extension = PurePath(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            "Formato no permitido. "
            "Se aceptan PDF, JPG, PNG, WebP, DOCX, XLSX, PPTX, TXT y CSV."
        )

    if uploaded_file.size > MAX_ATTACHMENT_SIZE:
        raise ValidationError(
            "Cada archivo puede ocupar como máximo 10 MB."
        )

    # Leer una muestra y devolver el puntero al principio.
    try:
        header = uploaded_file.read(8192)
    finally:
        uploaded_file.seek(0)

    if extension == ".pdf" and not header.startswith(b"%PDF-"):
        raise ValidationError("El contenido no parece ser un PDF válido.")

    if extension in {".jpg", ".jpeg"}:
        if not header.startswith(b"\xff\xd8\xff"):
            raise ValidationError("El contenido no parece ser una imagen JPEG válida.")

    if extension == ".png":
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationError("El contenido no parece ser una imagen PNG válida.")

    if extension == ".webp":
        if not (
            header.startswith(b"RIFF")
            and header[8:12] == b"WEBP"
        ):
            raise ValidationError("El contenido no parece ser una imagen WebP válida.")

    if extension in OFFICE_CONTENT_TYPES:
        required_prefix, required_content_type = OFFICE_CONTENT_TYPES[extension]

        try:
            with zipfile.ZipFile(uploaded_file) as archive:
                names = set(archive.namelist())

                if "[Content_Types].xml" not in names:
                    raise ValidationError(
                        "El documento de Office no tiene una estructura válida."
                    )

                content_types = archive.read(
                    "[Content_Types].xml"
                ).decode("utf-8", errors="strict")

                if (
                    not any(
                        name.startswith(required_prefix)
                        for name in names
                    )
                    or required_content_type not in content_types
                ):
                    raise ValidationError(
                        "La estructura del documento de Office no es válida."
                    )

        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
            raise ValidationError(
                "El documento de Office está dañado o no es válido."
            )
        finally:
            uploaded_file.seek(0)

    if extension in {".txt", ".csv"}:
        if b"\x00" in header:
            raise ValidationError(
                "El archivo de texto contiene datos binarios no permitidos."
            )

    uploaded_file.seek(0)