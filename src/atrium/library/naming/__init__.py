# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a path into what it says about the work.

**Pure**: paths in, structured results out, no filesystem access anywhere (003 plan section 3). That
is what lets `tests/corpus/naming.yaml` run as a plain table test with no fixtures on disk at all.

Nothing here raises on a name it does not understand. An unrecognised path is a result with a title
and nothing else, which is what plan section 5 requires - a scan that threw on a strange filename
would abort on somebody's real library rather than on ours.
"""

from atrium.library.naming.clean import (
    CleanName,
    clean_name,
    cut_at_release_metadata,
    from_text,
    is_tag,
)
from atrium.library.naming.external import (
    SUBTITLE_EXTENSIONS,
    ExternalName,
    language_of,
    parse_external,
)
from atrium.library.naming.movies import MovieParse, group, parse_movie
from atrium.library.naming.music import (
    PATH_ONLY,
    AudioParse,
    MetadataSource,
    PathOnly,
    parse_audio,
)
from atrium.library.naming.series import SPECIALS, EpisodeParse, parse_episode, season_of_directory

__all__ = [
    "PATH_ONLY",
    "SPECIALS",
    "SUBTITLE_EXTENSIONS",
    "AudioParse",
    "CleanName",
    "EpisodeParse",
    "ExternalName",
    "MetadataSource",
    "MovieParse",
    "PathOnly",
    "clean_name",
    "cut_at_release_metadata",
    "from_text",
    "group",
    "is_tag",
    "language_of",
    "parse_audio",
    "parse_episode",
    "parse_external",
    "parse_movie",
    "season_of_directory",
]
