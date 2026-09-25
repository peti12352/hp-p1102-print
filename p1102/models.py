from __future__ import annotations

from dataclasses import dataclass

from p1102.profile import PrinterProfile


@dataclass(frozen=True)
class PageRange:
    first: int = 1
    last: int | None = None

    @classmethod
    def all_pages(cls) -> PageRange:
        return cls(1, None)

    def scoped(self) -> bool:
        return self.first != 1 or self.last is not None

    def validate(self, total: int | None) -> None:
        if self.first < 1:
            raise RuntimeError("--from-page must be >= 1")
        if self.last is not None and self.last < self.first:
            raise RuntimeError("--to-page must be >= --from-page")
        if total is None:
            return
        if self.first > total:
            raise RuntimeError(f"from-page {self.first} exceeds document ({total} pages)")
        if self.last is not None and self.last > total:
            raise RuntimeError(f"to-page {self.last} exceeds document ({total} pages)")

    def cups_value(self) -> str:
        if self.last is None:
            return f"{self.first}-"
        if self.first == self.last:
            return str(self.first)
        return f"{self.first}-{self.last}"

    def sumatra_settings(self) -> str:
        if self.last is None:
            return f"{self.first}-"
        if self.first == self.last:
            return str(self.first)
        return f"{self.first}-{self.last}"

    def label(self) -> str:
        if not self.scoped():
            return "all pages"
        if self.last is None:
            return f"pages {self.first}-end"
        if self.first == self.last:
            return f"page {self.first}"
        return f"pages {self.first}-{self.last}"


@dataclass(frozen=True)
class UsbPrinter:
    sysfs: str
    vendor: str
    product: str
    serial: str
    product_name: str
    driver: str | None
    bus_dev: str | None

    def printable(self, profile: PrinterProfile) -> bool:
        return self.product in profile.printable_products()

    def smart_install(self, profile: PrinterProfile) -> bool:
        return self.product in profile.smart_install_products()

    def device_uri(self, profile: PrinterProfile) -> str:
        model = self.product_name
        brand = profile.uri_brand
        prefix = f"{brand} "
        if model.upper().startswith(prefix.upper()):
            model = model[len(prefix):]
        model = model.replace(" ", "%20")
        return f"usb://{brand}/{model}?serial={self.serial}"
