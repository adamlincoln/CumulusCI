import mock
import pytest

from github3.pulls import ShortPullRequest

from cumulusci.core.config import TaskConfig
from cumulusci.core.config import ServiceConfig
from cumulusci.tests.util import create_project_config
from cumulusci.core.exceptions import TaskOptionsError
from cumulusci.tasks.release_notes.task import GithubReleaseNotes
from cumulusci.tasks.release_notes.task import ParentPullRequestNotes
from cumulusci.tasks.github.tests.util_github_api import GithubApiTestMixin


class TestGithubReleaseNotes:
    @pytest.fixture
    def project_config(self):
        project_config = create_project_config()
        project_config.keychain.set_service(
            "github",
            ServiceConfig(
                {
                    "username": "TestUser",
                    "password": "TestPass",
                    "email": "testuser@testdomain.com",
                }
            ),
        )
        project_config.project__git__default_branch = "master"
        return project_config

    @mock.patch("cumulusci.tasks.release_notes.task.GithubReleaseNotesGenerator")
    def test_run_GithubReleaseNotes_task(
        self, GithubReleaseNotesGenerator, project_config
    ):
        generator = mock.Mock(return_value="notes")
        GithubReleaseNotesGenerator.return_value = generator
        task_config = TaskConfig({"options": {"tag": "release/1.0"}})
        task = GithubReleaseNotes(project_config, task_config)
        task.github = mock.Mock()
        task.get_repo = mock.Mock()
        task()
        generator.assert_called_once()


class TestParentPullRequestNotes(GithubApiTestMixin):

    BUILD_NOTES_LABEL = "Build Change Notes"
    PARENT_BRANCH_NAME = "feature/long-feature"
    CHILD_BRANCH_NAME = "feature/long-feature__child-branch"
    PARENT_BRANCH_OPTIONS = {
        "options": {
            "branch_name": PARENT_BRANCH_NAME,
            "build_notes_label": BUILD_NOTES_LABEL,
        }
    }
    CHILD_BRANCH_OPTIONS = {
        "options": {
            "branch_name": CHILD_BRANCH_NAME,
            "build_notes_label": BUILD_NOTES_LABEL,
        }
    }

    @pytest.fixture
    def project_config(self):
        project_config = create_project_config()
        project_config.keychain.set_service(
            "github",
            ServiceConfig(
                {
                    "username": "TestUser",
                    "password": "TestPass",
                    "email": "testuser@testdomain.com",
                }
            ),
        )
        return project_config

    @pytest.fixture
    def task_factory(self, project_config):
        def _task_factory(options):
            task_config = TaskConfig(options)
            task = ParentPullRequestNotes(project_config, task_config)
            task.repo = mock.Mock()
            task.repo.default_branch = "master"
            task.repo.owner.login = "SFDO-Tooling"
            task.logger = mock.Mock()
            task.github = mock.Mock()
            return task

        return _task_factory

    def test_setup_self(self, task_factory):
        task = task_factory(self.PARENT_BRANCH_OPTIONS)
        task._setup_self()

        assert task.repo is not None
        assert task.commit is not None
        assert task.generator is not None
        assert task.branch_name is not None

    def test_has_parent_branch(self, task_factory):
        task = task_factory(self.PARENT_BRANCH_OPTIONS)
        task.branch_name = "feature/parent_branch_naming_convention"
        assert task._has_parent_branch()
        task.branch_name = "feature/child__branch_naming_convention"
        assert not task._has_parent_branch()

    def test_commit_is_merge(self, task_factory):
        task = task_factory(self.PARENT_BRANCH_OPTIONS)
        task.commit = mock.Mock()
        task.commit.parents = [1, 2]
        assert task._commit_is_merge()

        task.commit.parents = [1]
        assert not task._commit_is_merge()

    @mock.patch("cumulusci.tasks.release_notes.task.get_pull_requests_with_base_branch")
    def test_get_parent_pull_request__parent_pull_request_exists(
        self, get_pull_request, task_factory, project_config, gh_api
    ):
        self.init_github()
        self.project_config = project_config  # GithubApiMixin wants this
        get_pull_request.return_value = [
            ShortPullRequest(self._get_expected_pull_request(1, 1, "Body"), gh_api)
        ]

        task = task_factory(self.PARENT_BRANCH_OPTIONS)
        task._setup_self()
        task.repo.default_branch = "master"

        actual_pull_request = task._get_parent_pull_request()
        get_pull_request.assert_called_once_with(
            task.repo, "master", self.PARENT_BRANCH_NAME
        )
        assert 1 == actual_pull_request.number
        assert "Body" == actual_pull_request.body

    @mock.patch("cumulusci.tasks.release_notes.task.get_pull_requests_with_base_branch")
    @mock.patch("cumulusci.tasks.release_notes.task.create_pull_request")
    @mock.patch("cumulusci.tasks.release_notes.task.add_labels_to_pull_request")
    def test_get_parent_pull_request__create_parent_pull_request(
        self,
        add_labels,
        create_pull_request,
        get_pull_request,
        task_factory,
        project_config,
        gh_api,
    ):
        self.init_github()
        self.project_config = project_config  # GithubApiMixin wants this

        get_pull_request.return_value = []
        create_pull_request.return_value = ShortPullRequest(
            self._get_expected_pull_request(62, 62, "parent body"), gh_api
        )

        task = task_factory(self.PARENT_BRANCH_OPTIONS)
        task._setup_self()

        actual_pull_request = task._get_parent_pull_request()
        get_pull_request.assert_called_once_with(
            task.repo, task.repo.default_branch, self.PARENT_BRANCH_NAME
        )
        assert 62 == actual_pull_request.number
        assert "parent body" == actual_pull_request.body

    @mock.patch("cumulusci.tasks.release_notes.task.is_label_on_pull_request")
    @mock.patch("cumulusci.tasks.release_notes.task.ParentPullRequestNotesGenerator")
    def test_run_task__label_not_found(
        self, notes_generator, label_found, task_factory, project_config, gh_api
    ):
        self.init_github()
        self.project_config = project_config  # GithubApiMixin wants this
        label_found.return_value = False
        notes_generator.retun_value = mock.Mock()
        child_branch_name = "feature/child__branch1"

        task = task_factory(self.PARENT_BRANCH_OPTIONS)
        task.logger = mock.Mock()
        task._commit_is_merge = mock.Mock(return_value=True)
        task._get_child_branch_name_from_merge_commit = mock.Mock(
            return_value=child_branch_name
        )
        task.repo = mock.Mock()
        task.repo.owner.login = "SFDO-Tooling"

        pull_request = ShortPullRequest(
            self._get_expected_pull_request(1, 1, "Body"), gh_api
        )
        pull_request.base.ref = "feature/cool-new-thing"
        task._get_parent_pull_request = mock.Mock(return_value=pull_request)

        task._run_task()
        task.generator.update_unaggregated_pr_header.assert_called_once_with(
            pull_request, child_branch_name
        )
        assert not task.generator.aggregate_child_change_notes.called

