"""Views for user profile display, update, and redirect."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import QuerySet
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, RedirectView, UpdateView

from apps.users.models import User


class UserDetailView(LoginRequiredMixin, DetailView):
    """Display a user's profile detail page."""

    model = User
    slug_field = "id"
    slug_url_kwarg = "id"


user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    """Allow authenticated users to update their own profile name."""

    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    def get_success_url(self) -> str:
        """Return the URL to redirect to after a successful update.

        Returns:
            The absolute URL of the current user's detail page.
        """
        assert self.request.user.is_authenticated  # type guard
        return self.request.user.get_absolute_url()

    def get_object(self, queryset: QuerySet | None = None) -> User:
        """Return the current authenticated user as the object to update.

        Args:
            queryset: Optional queryset to use (ignored; always returns request user).

        Returns:
            The currently authenticated User instance.
        """
        assert self.request.user.is_authenticated  # type guard
        return self.request.user


user_update_view = UserUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):
    """Redirect authenticated users to their own profile detail page."""

    permanent = False

    def get_redirect_url(self) -> str:
        """Return the URL of the current user's detail page.

        Returns:
            The URL to redirect to.
        """
        return reverse("users:detail", kwargs={"pk": self.request.user.pk})


user_redirect_view = UserRedirectView.as_view()
