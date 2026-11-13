"""Service layer for the blogs app, providing data access for CMS content."""

from apps.blogs.models import (
    Announcements,
    ChangeLog,
    ChangelogEntry,
    PlanFooter,
    TutorialBlog,
)


class CMS:
    """Service class encapsulating queries for all CMS content types."""

    def __init__(self):
        self.__meta__()

    def __meta__(self):
        self.VERSION = "0.5"
        self.BUILD = "ALPHA"

    def get_change_log(self):
        """Retrieve the most recent change log entry.

        Returns:
            ChangeLog or None: The latest ChangeLog instance, or None if none exist.
        """
        try:
            return ChangeLog.objects.order_by("-date_created")[0]
        except ChangeLog.DoesNotExist:
            return ChangeLog.objects.none()
        except IndexError:
            return None

    def get_announcement(self):
        """Retrieve the most recent announcement.

        Returns:
            Announcements or None: The latest Announcements instance, or None if none exist.
        """
        try:
            return Announcements.objects.order_by("-date_created")[0]
        except Announcements.DoesNotExist:
            return Announcements.objects.none()
        except IndexError:
            return None

    def get_tutorial_blogs(self):
        """Retrieve all tutorial blogs ordered by creation date descending.

        Returns:
            QuerySet or None: A queryset of TutorialBlog instances, or None on error.
        """
        try:
            return TutorialBlog.objects.order_by("-date_created")
        except TutorialBlog.DoesNotExist:
            return TutorialBlog.objects.none()
        except IndexError:
            return None

    def get_tutorial_info_blogs(self):
        """Retrieve tutorial blogs flagged as info buttons.

        Returns:
            QuerySet or None: A queryset of TutorialBlog instances with as_info_button=True.
        """
        try:
            return TutorialBlog.objects.filter(as_info_button=True).order_by(
                "-date_created"
            )
        except TutorialBlog.DoesNotExist:
            return None
        except IndexError:
            return None

    def get_tutorial_data(self, title):
        """Retrieve a single tutorial blog by its title.

        Args:
            title: The exact title of the tutorial to look up.

        Returns:
            TutorialBlog or None: The matching instance, or None if not found.
        """
        try:
            return TutorialBlog.objects.filter(title=title).get()
        except TutorialBlog.DoesNotExist:
            return TutorialBlog.objects.none()
        except Exception:
            return None

    def get_plan_footer(self):
        """Retrieve the most recent plan footer entry.

        Returns:
            PlanFooter or None: The latest PlanFooter instance, or None if not found.
        """
        try:
            return PlanFooter.objects.latest("date_created")[0]
        except PlanFooter.DoesNotExist:
            return None

    def get_changelog_entries(self):
        """Retrieve all published changelog entries ordered by date descending.

        Returns:
            QuerySet: A queryset of published ChangelogEntry instances.
        """
        return ChangelogEntry.objects.filter(is_published=True).order_by("-date")

    def get_home_banner(self):
        """Retrieve the home banner data containing the latest change log and announcement.

        Returns:
            dict: A dictionary with 'change_log' and 'announcement' keys.
        """
        response = {
            "change_log": self.get_change_log(),
            "announcement": self.get_announcement(),
        }
        return response
