from saya import Vk
from social_ethosa import BetterBotBase
from datetime import datetime, timedelta
import regex
import requests

import config
import patterns

from tokens import BotToken
from userbot import UserBot

base = BetterBotBase("users", "dat")
base.addPattern("rating", 0)
base.addPattern("programming_languages", [])
base.addPattern("github_profile", "")
base.addPattern("current", [])
base.addPattern("current_sub", [])

class V(Vk):
    def __init__(self):
        Vk.__init__(self, token=BotToken, group_id=config.bot_group_id, debug=True)
        self.messages_to_delete = {}
        self.userbot = UserBot()
        self.debug = True

    def message_new(self, event):
        """
        Handling all new messages.
        """
        event = event["object"]["message"]

        if event['peer_id'] in self.messages_to_delete:
            peer = 2e9 + config.userbot_chats[event['peer_id']]
            new_messages_to_delete = []
            ids = []

            for item in self.messages_to_delete[event['peer_id']]:
                if item['date'] > datetime.now():
                    new_messages_to_delete.append(item)
                else:
                    ids.append(item['id'])

            if new_messages_to_delete:
                self.messages_to_delete[event['peer_id']] = new_messages_to_delete
            else:
                self.messages_to_delete.pop(event['peer_id'])

            if ids:
                self.userbot.delete_messages(ids, peer)

        user = base.autoInstall(event["from_id"], self) if event["from_id"] > 0 else None

        message = event["text"].lstrip("/")
        messages = self.get_messages(event)
        selected_message = messages[0] if len(messages) == 1 else None
        selected_user = base.autoInstall(selected_message["from_id"], self) if selected_message else None
        is_bot_selected = selected_message and (selected_message["from_id"] < 0)

        match = regex.match(patterns.HELP, message)
        if match:
            return self.send_help(event)
        match = regex.match(patterns.KARMA, message)
        if match:
            return self.send_karma(event, selected_user if selected_user else user, not selected_user)
        match = regex.match(patterns.TOP, message)
        if match:
            maximum_users = match.group("maximum_users")
            maximum_users = int(maximum_users) if maximum_users else 0
            return self.send_top(event, maximum_users)
        match = regex.match(patterns.BOTTOM, message)
        if match:
            maximum_users = match.group("maximum_users")
            maximum_users = int(maximum_users) if maximum_users else 0
            return self.send_bottom(event, maximum_users)
        match = regex.match(patterns.INFO, message)
        if match:
            return self.send_info(event, selected_user if selected_user else user, not selected_user)
        match = regex.match(patterns.APPLY_KARMA, message)
        if match:
            # Only for chat rooms
            if event["peer_id"] < 2e9:
                return
            # Only for whitelisted chat rooms
            if event["peer_id"] not in config.chats_whitelist:
                self.send_not_in_whitelist(event, user)
                return
            # Only regular users can be selected
            if is_bot_selected:
                return

            if selected_user and (user.uid != selected_user.uid):
                operator = match.group("operator")[0]
                amount = match.group("amount")
                amount = int(amount) if amount else 0

                # Downvotes disabled for users with negative rating
                if (operator == "-") and (user.rating < 0):
                    self.send_not_enough_karma_error(event, user)
                    return

                user_karma_change, selected_user_karma_change, voters = self.apply_karma_change(event, user, selected_user, operator, amount)
                base.save(selected_user)
                if user_karma_change:
                    base.save(user)
                self.send_karma_change(event, user_karma_change, selected_user_karma_change, voters)
                self.delete_message(event)
                return
        match = regex.match(patterns.ADD_PROGRAMMING_LANGUAGE, message)
        if match:
            language = match.group('language')
            language = self.get_default_programming_language(language)
            if not language:
                return
            if language not in user.programming_languages:
                user.programming_languages.append(language)
                base.save(user)
            return self.send_programming_languages_list(event, user)
        match = regex.match(patterns.REMOVE_PROGRAMMING_LANGUAGE, message)
        if match:
            language = match.group('language')
            language = self.get_default_programming_language(language)
            if not language:
                return
            if language in user.programming_languages:
                user.programming_languages.remove(language)
                base.save(user)
            return self.send_programming_languages_list(event, user)
        match = regex.match(patterns.ADD_GITHUB_PROFILE, message)
        if match:
            profile = match.group('profile')
            if not profile:
                return
            if profile != user.github_profile:
                if requests.get(f'https://github.com/{profile}').status_code == 200:
                    user.github_profile = profile
                    base.save(user)
            return self.send_github_profile(event, user)
        match = regex.match(patterns.REMOVE_GITHUB_PROFILE, message)
        if match:
            profile = match.group('profile')
            if not profile:
                return
            if profile == user.github_profile:
                user.github_profile = ""
                base.save(user)
            return self.send_github_profile(event, user)
        match = regex.match(patterns.TOP_LANGUAGES, message)
        if match:
            languages = match.group("languages")
            return self.send_top_languages(event, languages)

    def delete_message(self, event, delay=2):
        peer_id = event['peer_id']
        if peer_id in config.userbot_chats and peer_id in config.chats_deleting:
            if peer_id not in self.messages_to_delete:
                self.messages_to_delete.update({peer_id: []})

            message_id = event['conversation_message_id']
            data = {'date': datetime.now() + timedelta(seconds=delay), 'id': message_id}
            self.messages_to_delete[peer_id].append(data)

    def apply_karma_change(self, event, user, selected_user, operator, amount):
        selected_user_karma_change = None
        user_karma_change = None
        voters = None

        # Personal karma transfer
        if amount > 0:
            if user.rating < amount:
                self.send_not_enough_karma_error(event, user)
                return user_karma_change, selected_user_karma_change, voters
            else:
                user_karma_change = self.apply_user_karma(user, -amount)
                amount = -amount if operator == "-" else amount
                selected_user_karma_change = self.apply_user_karma(selected_user, amount)

        # Collective vote
        elif amount == 0:
            if operator == "+":
                selected_user_karma_change, voters = self.apply_collective_vote(user, selected_user, "current", config.positive_votes_per_karma, +1)
            else:
                selected_user_karma_change, voters = self.apply_collective_vote(user, selected_user, "current_sub", config.negative_votes_per_karma, -1)

        return user_karma_change, selected_user_karma_change, voters

    def apply_collective_vote(self, user, selected_user, current_voters, number_of_voters, amount):
        if user.uid not in selected_user[current_voters]:
            selected_user[current_voters].append(user.uid)
        if len(selected_user[current_voters]) >= number_of_voters:
            voters = selected_user[current_voters]
            selected_user[current_voters] = []
            return self.apply_user_karma(selected_user, amount), voters
        return None, None

    def apply_user_karma(self, user, amount):
        user.rating += amount
        return (user.uid, user.name, user.rating - amount, user.rating)

    def get_messages(self, event):
        reply_message = event.get("reply_message", {})
        return [reply_message] if reply_message else event.get("fwd_messages", [])

    def get_programming_languages_string_with_parentheses_or_empty(self, user):
        programming_languages_string = self.get_programming_languages_string(user)
        if programming_languages_string == "":
            return programming_languages_string
        else:
            return "(" + programming_languages_string + ")"

    def get_github_profile(self, user):
        if isinstance(user, dict):
            return user["github_profile"] if "github_profile" in user else ""
        else:
            return user.github_profile

    def get_github_profile_top_string(self, user):
        profile = self.get_github_profile(user)
        if profile:
            profile = f" — github.com/{profile}"
        return profile

    def get_programming_languages_string(self, user):
        if isinstance(user, dict):
            languages = user["programming_languages"] if "programming_languages" in user else []
        else:
            languages = user.programming_languages
        if len(languages) > 0:
            languages.sort()
            return ", ".join(languages)
        else:
            return ""

    def get_default_programming_language(self, language):
        for default_programming_language in config.default_programming_languages:
            default_programming_language = default_programming_language.replace('\\', '')
            if default_programming_language.lower() == language.lower():
                return default_programming_language
        return None

    def contains_string(self, strings, matchedString, ignoreCase):
        if ignoreCase:
            for string in strings:
                if string.lower() == matchedString.lower():
                    return True
        else:
            for string in strings:
                if string == matchedString:
                    return True
        return False

    def contains_all_strings(self, strings, matchedStrings, ignoreCase):
        matched_strings_count = len(matchedStrings)
        for string in strings:
            if self.contains_string(matchedStrings, string, ignoreCase):
                matched_strings_count -= 1
                if matched_strings_count == 0:
                    return True
        return False

    def send_karma_change(self, event, user_karma_change, selected_user_karma_change, voters):
        if selected_user_karma_change and user_karma_change:
            self.send_message(event, "Карма изменена: [id%s|%s] [%s]->[%s], [id%s|%s] [%s]->[%s]." % (user_karma_change + selected_user_karma_change))
        elif selected_user_karma_change:
            self.send_message(event, "Карма изменена: [id%s|%s] [%s]->[%s]. Голосовали: (%s)" % (selected_user_karma_change + (", ".join([f"@id{voter}" for voter in voters]),)))

    def send_karma(self, event, user, is_self=True):
        if is_self:
            response = "[id%s|%s], Ваша карма — %s."
        else:
            response = "Карма [id%s|%s] — %s."
        self.send_message(event, response % (user.uid, user.name, self.get_karma_string(user)))

    def send_info(self, event, user, is_self=True):
        programming_languages_string = self.get_programming_languages_string(user)
        if not programming_languages_string:
            programming_languages_string = "отсутствуют"
        profile = self.get_github_profile(user)
        if not profile:
            profile = "отсутствует"
        else:
            profile = f"github.com/{profile}"
        if is_self:
            response = "[id%s|%s], Ваша карма — %s.\nВаши языки программирования: %s\nВаша страничка на GitHub — %s"
        else:
            response = "Карма [id%s|%s] — %s.\nЯзыки программирования: %s\nВаша страничка на GitHub — %s"
        self.send_message(event, response % (user.uid, user.name, self.get_karma_string(user), programming_languages_string, profile))

    def get_karma_string(self, user):
        plus_string = ""
        minus_string = ""
        if isinstance(user, dict):
            karma = user["rating"]
            plus_votes = len(user["current"])
            minus_votes = len(user["current_sub"])
        else:
            karma = user.rating
            plus_votes = len(user.current)
            minus_votes = len(user.current_sub)
        if plus_votes > 0:
            plus_string = "+%.1f" % (plus_votes / config.positive_votes_per_karma)
        if minus_votes > 0:
            minus_string = "-%.1f" % (minus_votes / config.negative_votes_per_karma)
        if plus_votes > 0 or minus_votes > 0:
            return f"[{karma}][{plus_string}{minus_string}]"
        else:
            return f"[{karma}]"

    def send_top_users(self, event, users):
        if not users:
            return
        user_strings = ["%s [id%s|%s]%s %s" % (self.get_karma_string(user), user["uid"], user["name"], self.get_github_profile_top_string(user), self.get_programming_languages_string_with_parentheses_or_empty(user)) for user in users]
        total_symbols = 0
        i = 0
        for user_string in user_strings:
            user_string_length = len(user_string)
            if (total_symbols + user_string_length + 2) >= 4096: # Maximum message size for VK API (messages.send)
                user_strings = user_strings[:i]
            else:
                total_symbols += user_string_length + 2
                i += 1
        response = "\n".join(user_strings)
        self.send_message(event, response)

    def get_users_sorted_by_karma(self):
        return base.getSortedByKeys("rating", otherKeys=["programming_languages", "current", "current_sub", "github_profile"])

    def send_bottom(self, event, maximum_users):
        users = self.get_users_sorted_by_karma()
        users = [i for i in users if (i["rating"] != 0) or ("programming_languages" in i and len(i["programming_languages"]) > 0)]
        if (maximum_users > 0) and (len(users) >= maximum_users):
            users.reverse()
            self.send_top_users(event, users[:maximum_users])
        else:
            self.send_top_users(event, reversed(users))

    def send_top(self, event, maximum_users):
        users = self.get_users_sorted_by_karma()
        users = [i for i in users if (i["rating"] != 0) or ("programming_languages" in i and len(i["programming_languages"]) > 0)]
        if (maximum_users > 0) and (len(users) >= maximum_users):
            self.send_top_users(event, users[:maximum_users])
        else:
            self.send_top_users(event, users)

    def send_top_languages(self, event, languages):
        languages = regex.split(r"\s+", languages)
        users = self.get_users_sorted_by_karma()
        users = [i for i in users if ("programming_languages" in i and len(i["programming_languages"]) > 0) and self.contains_all_strings(i["programming_languages"], languages, True)]
        self.send_top_users(event, users)

    def send_github_profile(self, event, user):
        profile = self.get_github_profile(user)
        if not profile:
            self.send_message(event, f"[id{user.uid}|{user.name}], у Вас не указана страничка на GitHub.")
        else:
            self.send_message(event, f"[id{user.uid}|{user.name}], Ваша страничка на GitHub — github.com/{profile}.")

    def send_programming_languages_list(self, event, user):
        programming_languages_string = self.get_programming_languages_string(user)
        if not programming_languages_string:
            self.send_message(event, f"[id{user.uid}|{user.name}], у Вас не указано языков программирования.")
        else:
            self.send_message(event, f"[id{user.uid}|{user.name}], Ваши языки программирования: {programming_languages_string}.")

    def send_help(self, event):
        self.send_message(event, config.help_string)

    def send_not_in_whitelist(self, event, user):
        peer_id = event["peer_id"]
        message = f"Извините, [id{user.uid}|{user.name}], но Ваша беседа [{peer_id}] отсутствует в белом списке для начисления кармы."
        self.send_message(event, message)

    def send_not_enough_karma_error(self, event, user):
        message = f"Извините, [id{user.uid}|{user.name}], но Вашей кармы [{user.rating}] недостаточно :("
        self.send_message(event, message)

    def send_message(self, event, message):
        self.messages.send(message=message, peer_id=event["peer_id"], disable_mentions=1, random_id=0)


if __name__ == '__main__':
    vk = V()
    vk.start_listen()
