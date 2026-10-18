from django.urls import path

from ibolit.articles.api import views

urlpatterns = [
    path("articles/categories", views.ArticleCategoriesView.as_view(), name="article-categories"),
    path("articles/picked", views.PickedArticlesView.as_view(), name="articles-picked"),
    path("articles", views.ArticleListView.as_view(), name="articles"),
    path("articles/<slug:slug>", views.ArticleDetailView.as_view(), name="article-detail"),
]
