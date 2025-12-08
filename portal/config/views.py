"""Simple views for the portal."""

from django.http import HttpResponse


def home(request):
    """Landing page."""
    if request.user.is_authenticated:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Shifter Portal</title></head>
        <body>
            <h1>Shifter Portal</h1>
            <p>Welcome, {request.user.username}</p>
            <p><a href="/oidc/logout/">Logout</a></p>
        </body>
        </html>
        """
    else:
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Shifter Portal</title></head>
        <body>
            <h1>Shifter Portal</h1>
            <p><a href="/oidc/authenticate/">Login with Cognito</a></p>
        </body>
        </html>
        """
    return HttpResponse(html)
