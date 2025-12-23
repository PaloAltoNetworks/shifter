"""URL routing for Documentation views."""

from django.urls import path, re_path

from documentation import views

app_name = "documentation"

urlpatterns = [
    path("", views.doc_index, name="index"),
    # Catch-all for nested paths like "portal/design-system"
    re_path(r"^(?P<path>.+)/$", views.doc_page, name="page"),
]
