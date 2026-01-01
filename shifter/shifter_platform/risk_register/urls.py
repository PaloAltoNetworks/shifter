"""URL routing for Risk Register UI views."""

from django.urls import path

from risk_register import views

app_name = "risk_register"

urlpatterns = [
    # Risk views
    path("", views.risk_list, name="risk_list"),
    path("risks/<int:pk>/", views.risk_detail, name="risk_detail"),
    path("risks/create/", views.risk_create, name="risk_create"),
    path("risks/<int:pk>/edit/", views.risk_edit, name="risk_edit"),
    path("risks/<int:pk>/delete/", views.risk_delete, name="risk_delete"),
    path("risks/<int:pk>/restore/", views.risk_restore, name="risk_restore"),
    path("risks/<int:pk>/close/", views.risk_close, name="risk_close"),
    path("risks/<int:pk>/reopen/", views.risk_reopen, name="risk_reopen"),
    # Comment views
    path("risks/<int:risk_pk>/comments/add/", views.comment_add, name="comment_add"),
    path(
        "risks/<int:risk_pk>/comments/<int:pk>/delete/",
        views.comment_delete,
        name="comment_delete",
    ),
    # API Key management
    path("api-keys/", views.apikey_list, name="apikey_list"),
    path("api-keys/create/", views.apikey_create, name="apikey_create"),
    path("api-keys/<int:pk>/revoke/", views.apikey_revoke, name="apikey_revoke"),
]
