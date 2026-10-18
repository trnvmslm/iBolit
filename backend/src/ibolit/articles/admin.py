from django.contrib import admin

from ibolit.articles.models import Article


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("title", "category", "read_minutes", "published_at")
    list_filter = ("category",)
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}  # noqa: RUF012
