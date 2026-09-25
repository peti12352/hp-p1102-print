CUPS_USB_BACKENDS = (
    "/usr/lib/cups/backend/usb",
    "/usr/libexec/cups/backend/usb",
    "/lib/cups/backend/usb",
)
TIMEOUT_SEC = 180
MAX_RETRIES = 3
RETRY_DELAY_SEC = 2
CONVERT_TIMEOUT_SEC = 120

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"})
TEXTUTIL_EXTENSIONS = frozenset({
    ".doc", ".docx", ".odt", ".rtf", ".txt", ".html", ".htm", ".wordml", ".webarchive",
})
LIBREOFFICE_EXTENSIONS = frozenset({
    ".doc", ".docx", ".odt", ".rtf", ".txt",
    ".xls", ".xlsx", ".ods",
    ".ppt", ".pptx", ".odp",
    ".html", ".htm",
}) | IMAGE_EXTENSIONS
SUPPORTED_EXTENSIONS = frozenset({".pdf"}) | LIBREOFFICE_EXTENSIONS

BLANK_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R>>endobj
trailer<</Size 4/Root 1 0 R>>
startxref
168
%%EOF
"""
