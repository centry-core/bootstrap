#!/usr/bin/python3
# coding=utf-8

#   Copyright 2022 getcarrier.io
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

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611


class RepoResolver:
    """ Repo resolver """

    def __init__(self, module, repo_config):
        self.module = module
        self.repo_config = repo_config
        #
        self.sub_resolvers = list()
        self.plugin_repo = None

    def init(self):
        """ Init resolver """
        if isinstance(self.repo_config, list):
            for config in self.repo_config:
                sub_resolver = RepoResolver(self.module, config)
                sub_resolver.init()
                self.sub_resolvers.append(sub_resolver)
        #
        elif self.repo_config["type"] == "resource":
            log.info("Loading plugin repository from resource: %s", self.repo_config["name"])
            self.plugin_repo = json.loads(
                self.module.descriptor.loader.get_data(self.repo_config["name"])
            )
        #
        elif self.repo_config["type"] == "config":
            log.info("Loading plugin repository from config")
            self.plugin_repo = self.repo_config["data"]

    def resolve(self, plugin):
        """ Resolve plugin """
        for sub_resolver in self.sub_resolvers:
            sub_result = sub_resolver.resolve(plugin)
            if sub_result is not None:
                return sub_result
        #
        if self.plugin_repo is None:
            return None
        #
        return self.plugin_repo.get(plugin, None)

    def deinit(self):  # pylint: disable=R0201
        """ De-init resolver """
        while self.sub_resolvers:
            sub_resolver = self.sub_resolvers.pop(0)
            sub_resolver.deinit()
