#!/usr/bin/python3
# coding=utf-8

#   Copyright 2023 getcarrier.io
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

""" Repo tools """

import json
import importlib

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611


class RepoResolver:
    """ Repo resolver """

    def __init__(self, module, repo_config):
        self.module = module
        self.repo_config = repo_config
        #
        self.sub_resolvers = []
        #
        self.metadata_provider = None
        self.source_provider = None
        #
        self.lookup = self._local_lookup
        self.lookup_data = None

    def _local_lookup(self, plugin):
        if self.lookup_data is None:
            return None
        #
        return self.lookup_data.get(plugin, None)

    def _github_lookup(self, plugin):
        whitelist = self.repo_config.get("whitelist", None)
        if whitelist is not None and plugin not in whitelist:
            return None
        #
        namespace = self.repo_config.get("namespace", "centry-core")
        branch = self.repo_config.get("branch", "main")
        file = self.repo_config.get("metadata_file", "metadata.json")
        #
        metadata_url = f"https://raw.githubusercontent.com/{namespace}/{plugin}/{branch}/{file}"
        try:
            self.metadata_provider.get_metadata({"source": metadata_url})
        except:  # pylint: disable=W0702
            return None
        #
        return {
            "source": {
                "type": "git",
                "source": f"https://github.com/{namespace}/{plugin}.git",
                "branch": branch
            },
            "objects": {
                "metadata": metadata_url
            }
        }

    def init(self):
        """ Init resolver """
        if isinstance(self.repo_config, list):
            for config in self.repo_config:
                sub_resolver = RepoResolver(self.module, config)
                sub_resolver.init()
                self.sub_resolvers.append(sub_resolver)
            #
            return
        #
        repo_type = self.repo_config.get("type", "github")
        #
        if repo_type == "resource":
            log.info("Loading plugin repository from resource: %s", self.repo_config["name"])
            self.lookup_data = json.loads(
                self.module.descriptor.loader.get_data(self.repo_config["name"])
            )
        #
        elif repo_type == "config":
            log.info("Loading plugin repository from config")
            self.lookup_data = self.repo_config["data"]
        #
        elif repo_type == "config_key":
            config_key = self.repo_config["name"]
            if config_key not in self.module.descriptor.config:
                return
            log.info("Loading plugin repository from config key")
            self.lookup_data = self.module.descriptor.config[config_key]
        #
        elif repo_type == "github":
            log.info("Using GitHub plugin repository")
            self.lookup = self._github_lookup
        #
        else:
            return
        #
        # Metadata
        #
        metadata_config = self.repo_config.get("metadata_provider", None)
        if metadata_config is None:
            metadata_config = {
                "type": "pylon.core.providers.metadata.http",
            }
        #
        metadata_config = metadata_config.copy()
        metadata_provider_type = metadata_config.pop("type")
        #
        self.metadata_provider = importlib.import_module(
            metadata_provider_type
        ).Provider(self.module.context, metadata_config)
        self.metadata_provider.init()
        #
        # Source
        #
        source_config = self.repo_config.get("source_provider", None)
        if source_config is None:
            source_config = {
                "type": "pylon.core.providers.source.git",
                "delete_git_dir": False,
                "depth": None,
            }
        #
        source_config = source_config.copy()
        source_provider_type = source_config.pop("type")
        #
        self.source_provider = importlib.import_module(
            source_provider_type
        ).Provider(self.module.context, source_config)
        self.source_provider.init()

    def resolve(self, plugin):
        """ Resolve plugin """
        for sub_resolver in self.sub_resolvers:
            sub_result = sub_resolver.resolve(plugin)
            if sub_result is not None:
                return sub_result
        #
        return self.lookup(plugin)

    def get_metadata_provider(self, plugin):
        """ Get metadata provider for plugin """
        for sub_resolver in self.sub_resolvers:
            sub_result = sub_resolver.get_metadata_provider(plugin)
            if sub_result is not None:
                return sub_result
        #
        if self.lookup(plugin) is None:
            return None
        #
        return self.metadata_provider

    def get_source_provider(self, plugin):
        """ Get source provider for plugin """
        for sub_resolver in self.sub_resolvers:
            sub_result = sub_resolver.get_source_provider(plugin)
            if sub_result is not None:
                return sub_result
        #
        if self.lookup(plugin) is None:
            return None
        #
        return self.source_provider

    def deinit(self):
        """ De-init resolver """
        while self.sub_resolvers:
            sub_resolver = self.sub_resolvers.pop(0)
            sub_resolver.deinit()
        #
        if self.source_provider is not None:
            self.source_provider.deinit()
        #
        if self.metadata_provider is not None:
            self.metadata_provider.deinit()
