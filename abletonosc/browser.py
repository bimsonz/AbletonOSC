from typing import Tuple, Any, Optional, List
from .handler import AbletonOSCHandler
import Live
import logging

logger = logging.getLogger("abletonosc")


class BrowserHandler(AbletonOSCHandler):
    def __init__(self, manager):
        super().__init__(manager)
        self.class_identifier = "browser"

    @property
    def browser(self):
        return Live.Application.get_application().browser

    def _find_item_recursive(self, parent, name, max_depth=4, current_depth=0):
        """
        Recursively search browser items for a match by name (case-insensitive).
        Returns the first loadable match, or None.
        """
        if current_depth > max_depth:
            return None

        try:
            children = list(parent.children)
        except Exception:
            return None

        for child in children:
            try:
                child_name = child.name
            except Exception:
                continue

            # Match exact, without extension, or as substring
            child_name_bare = child_name.rsplit(".", 1)[0] if "." in child_name else child_name
            name_lower = name.lower()
            if (child_name.lower() == name_lower or
                child_name_bare.lower() == name_lower or
                name_lower in child_name_bare.lower()):
                if child.is_loadable:
                    return child
                # If it's a folder with the right name, search inside it
                result = self._find_item_recursive(child, name, max_depth, current_depth + 1)
                if result:
                    return result

            if child.is_folder and current_depth < max_depth:
                result = self._find_item_recursive(child, name, max_depth, current_depth + 1)
                if result:
                    return result

        return None

    def _search_items(self, parent, query, results, max_results=20, max_depth=3, current_depth=0):
        """
        Search browser items, collecting matches where query appears in the name.
        """
        if current_depth > max_depth or len(results) >= max_results:
            return

        try:
            children = list(parent.children)
        except Exception:
            return

        for child in children:
            if len(results) >= max_results:
                return

            try:
                child_name = child.name
            except Exception:
                continue

            if query.lower() in child_name.lower() and child.is_loadable:
                results.append(child_name)

            if child.is_folder and current_depth < max_depth:
                self._search_items(child, query, results, max_results, max_depth, current_depth + 1)

    def _get_children_names(self, parent, loadable_only=False):
        """Get names of immediate children."""
        names = []
        try:
            for child in parent.children:
                try:
                    if loadable_only and not child.is_loadable and not child.is_folder:
                        continue
                    names.append(child.name)
                except Exception:
                    continue
        except Exception:
            pass
        return names

    def _get_category_root(self, category_name):
        """
        Get a top-level browser category by name.
        Tries browser attributes first (instruments, audio_effects, etc.),
        then falls back to searching root children.
        """
        category_map = {
            "instruments": "instruments",
            "drums": "drums",
            "audio_effects": "audio_effects",
            "midi_effects": "midi_effects",
            "sounds": "sounds",
            "packs": "packs",
            "samples": "samples",
            "clips": "clips",
            "max_for_live": "max_for_live",
        }

        attr_name = category_map.get(category_name.lower())
        if attr_name:
            try:
                return getattr(self.browser, attr_name)
            except (AttributeError, RuntimeError):
                pass

        # Fallback: search browser's user_folders or root items
        try:
            for folder in self.browser.user_folders:
                if folder.name.lower() == category_name.lower():
                    return folder
        except Exception:
            pass

        return None

    def _navigate_path(self, category, path_parts):
        """Navigate into a category by path segments."""
        current = category
        for part in path_parts:
            found = False
            try:
                for child in current.children:
                    if child.name.lower() == part.lower():
                        current = child
                        found = True
                        break
            except Exception:
                return None
            if not found:
                return None
        return current

    def init_api(self):
        def load_instrument(params: Tuple[Any]):
            """
            Load an instrument onto a track.
            /live/browser/load_instrument (name, track_index)
            Searches Instruments and Drums categories.
            """
            name = str(params[0])
            track_index = int(params[1])

            logger.info("Loading instrument '%s' onto track %d" % (name, track_index))

            # Select the target track
            track = self.song.tracks[track_index]
            self.song.view.selected_track = track

            # Search in instruments and drums categories
            item = None
            for category_name in ["instruments", "drums", "sounds"]:
                category = self._get_category_root(category_name)
                if category:
                    item = self._find_item_recursive(category, name)
                    if item:
                        break

            if not item:
                logger.error("Instrument not found: %s" % name)
                raise ValueError("Instrument not found: %s" % name)

            self.browser.load_item(item)
            logger.info("Loaded instrument: %s" % item.name)
            return (item.name,)

        def load_effect(params: Tuple[Any]):
            """
            Load an audio or MIDI effect onto a track.
            /live/browser/load_effect (name, track_index)
            """
            name = str(params[0])
            track_index = int(params[1])

            logger.info("Loading effect '%s' onto track %d" % (name, track_index))

            track = self.song.tracks[track_index]
            self.song.view.selected_track = track

            item = None
            for category_name in ["audio_effects", "midi_effects"]:
                category = self._get_category_root(category_name)
                if category:
                    item = self._find_item_recursive(category, name)
                    if item:
                        break

            if not item:
                logger.error("Effect not found: %s" % name)
                raise ValueError("Effect not found: %s" % name)

            self.browser.load_item(item)
            logger.info("Loaded effect: %s" % item.name)
            return (item.name,)

        def get_categories(params: Tuple[Any]):
            """
            List top-level browser categories.
            /live/browser/get/categories
            """
            categories = []
            for attr_name in ["instruments", "drums", "audio_effects", "midi_effects",
                              "sounds", "packs", "samples", "clips", "max_for_live"]:
                try:
                    cat = getattr(self.browser, attr_name)
                    if cat:
                        categories.append(attr_name)
                except (AttributeError, RuntimeError):
                    pass
            return tuple(categories)

        def get_children(params: Tuple[Any]):
            """
            List children of a browser path.
            /live/browser/get/children (category, [path_part1, path_part2, ...])
            """
            category_name = str(params[0])
            path_parts = [str(p) for p in params[1:]] if len(params) > 1 else []

            category = self._get_category_root(category_name)
            if not category:
                raise ValueError("Category not found: %s" % category_name)

            if path_parts:
                target = self._navigate_path(category, path_parts)
                if not target:
                    raise ValueError("Path not found: %s/%s" % (category_name, "/".join(path_parts)))
            else:
                target = category

            names = self._get_children_names(target)
            return tuple(names)

        def search(params: Tuple[Any]):
            """
            Search for browser items by name.
            /live/browser/search (query)
            """
            query = str(params[0])
            results = []

            for category_name in ["instruments", "drums", "audio_effects", "midi_effects", "sounds"]:
                category = self._get_category_root(category_name)
                if category:
                    self._search_items(category, query, results, max_results=20, max_depth=4)

            return tuple(results)

        self.osc_server.add_handler("/live/browser/load_instrument", load_instrument)
        self.osc_server.add_handler("/live/browser/load_effect", load_effect)
        self.osc_server.add_handler("/live/browser/get/categories", get_categories)
        self.osc_server.add_handler("/live/browser/get/children", get_children)
        self.osc_server.add_handler("/live/browser/search", search)
