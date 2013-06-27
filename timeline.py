"""Parse a Sycorax script into an annotated multi-author timeline."""

from datetime import datetime, timedelta
import json
import random
import re
import hashlib
import os
import pytz

# 10M: ~10 minutes later
# 4H: ~4 hours later
# 1D: the next day
# R: Reply to previous
# 10A: 10AM on the current day
# 9P: 9PM on the current day

DEFAULT_DELAY = timedelta(hours=4)
REPLY_TO_CODE = "R"
DELAY_CODE = re.compile("([0-9]+)([MHD])")
DELAY_UNITS = dict(M="minutes", H="hours", D="days")
TIME_OF_DAY_CODE = re.compile("([0-9]{1,2})([AP])")

JSON_TIME_FORMAT = "%d %b %Y %H:%M:%S %Z"

def load_config(directory):
    filename = os.path.join(directory, "config.json")
    if not os.path.exists(filename):
        raise Exception("Could not find config.json file in directory %s" % (
                directory
                ))

    data = json.loads(open(filename).read().strip())
    data['start_date'] = datetime.strptime(data['start_date'], "%Y/%m/%d")
    data['chapter_duration_days'] = timedelta(
        days=data['chapter_duration_days'])
    return data

def load_stream(directory):
    config = load_config(directory)
    filename = os.path.join(directory, "input.txt")
    if not os.path.exists(filename):
        raise Exception("Could not find input.txt file in directory %s" % (
                directory
                ))

    progress = load_progress(directory)
    try:
        progress = load_progress(directory)
    except Exception, e:
        # Nothing has been posted yet.
        progress = None

    return Stream(open(filename), config=config, progress=progress)


def load_progress(directory):
    config = load_config(directory)
    filename = os.path.join(directory, "progress.json")
    if not os.path.exists(filename):
        raise Exception("Could not find progress.json file in directory %s" % (
                directory
                ))
    return Progress(open(filename))


class TimezoneAware(object):

    def start_of_day(self, datetime):
        return datetime.replace(
            hour=0, minute=0, second=0, tzinfo=self.timezone)


class Progress(object):
    """The progress made in posting a stream."""

    def __init__(self, input_stream):
        self.timeline = [json.loads(line.strip()) for line in input_stream]
        self.posts = {}
        for post in self.timeline:
            self.posts[post['internal_id']] = post

class TweetParser(TimezoneAware):

    """Parses a line of script into a tweet."""

    def __init__(self, config, progress=None, fuzz_quotient=0.2,
                 fuzz_minimum_seconds=120):
        self.authors = config['authors']
        self.timezone = pytz.timezone(config['timezone'])
        for author in self.authors:
            author['account'] = author['account'].encode("utf8")
            author['css_class'] = author['account'].replace(
                '-', '').replace('_', '')
            author['color'] = author.get('color', 'white').encode("utf8")
            author['code'] = author.get('code', '')
        fuzz = float(config.get('fuzz', fuzz_quotient))
        self.fuzz_quotient = fuzz
        self.fuzz_minimum_seconds = int(config.get('fuzz_minimum_seconds', fuzz_minimum_seconds))
        self.start_date=config['start_date']
        self.config = config
        self.progress = progress

        self.default_author = None
        self.authors_by_code = {}
        for author in self.authors:
            code = author.get('code', '')
            if code == '':
                self.default_author = author
            self.authors_by_code[code] = author

    def parse(self, line, stream_so_far):
        is_command = False

        author = self.default_author
        reply_to = None
        delay = None
        hour_of_day = None

        if stream_so_far.latest_tweet is None:
            # This is the first tweet ever. The base timecode is the
            # start date.
            base_timecode = self.start_of_day(self.start_date)
        elif stream_so_far.current_chapter.total_tweets == 0:
            # This is the first tweet of the chapter. The base timecode
            # is the chapter start date.
            base_timecode = stream_so_far.current_chapter.start_date
        else:
            # There is no base timecode. The timestamp will be calculated
            # based on the previous tweet's timestamp.
            base_timecode = None

        line = line.strip()

        command_and_tweet = line.split(" ", 1)
        if len(command_and_tweet) > 1:
            command, tweet = command_and_tweet
        else:
            # Single-word tweet.
            return Tweet(line, author, base_timecode, self.timezone,
                         progress=self.progress)

        # The "command" may actually be the first word of the tweet.
        # Extract commands from it until there's nothing left.
        # If there is something left, it's not a command.
        for author_code, possible_author in self.authors_by_code.items():
            if author_code != "" and author_code in command:
                author = possible_author
                command = command.replace(author_code, "", 1)
                break

        is_reply = False
        if REPLY_TO_CODE in command:
            reply_to = stream_so_far.latest_tweet
            command = command.replace(REPLY_TO_CODE, "", 1)
            is_reply = True

        match = DELAY_CODE.match(command)
        if match is not None:
            number, unit = match.groups()
            subcommand = "".join(match.groups())
            command = command.replace(subcommand, "")
            kwargs = { DELAY_UNITS[unit]: int(number) }
            delay = timedelta(**kwargs)

        match = TIME_OF_DAY_CODE.match(command)
        if match is not None:
            hour, am = match.groups()
            subcommand = "".join(match.groups())
            command = command.replace(subcommand, "")
            hour = int(hour)
            if am == "A" and hour == 12:
                hour = 0
            if am == "P" and hour != 12:
                hour += 12
            if hour > 23:
                raise ValueError("Bad time of day %s in %s" % (
                        subcommand, line))
            hour_of_day = hour

        if command == "":
            # The first word has been entirely processed as
            # commands. The rest of the line is the actual content.
            line = tweet
        else:
            # The first word was not a command.
            author = self.default_author
            reply_to = None
            delay = None
            is_reply = False

        if is_reply and stream_so_far.latest_tweet is None:
            raise ValueError(
                "The first tweet in the script cannot be a reply.")

        if delay is None and hour_of_day is None:
            if len(stream_so_far.current_day.tweets) == 0 and stream_so_far.current_chapter.total_tweets > 0:
                # This is the first tweet of an in-story day, and no
                # special date instructions were given, so publish it at
                # the start of the next real-world day.
                base_timecode = self.start_of_day(base_timecode) + timedelta(
                    days=1)

            elif stream_so_far.current_chapter.total_tweets == 0:
                delay = timedelta(minutes=0)

        if len(line) > 140:
            print '[WARNING] %d characters in "%s"' % (len(line), line)
        return Tweet(line, author, base_timecode, self.timezone, delay,
                     hour_of_day, reply_to, self.progress)

class Chapter:

    def __init__(self, name, start_date):
        self.name = name
        self.days = []
        self.start_date = start_date

    @property
    def in_story_timeline_html(self):
        return "\n".join(
            ["<h2>%s</h2>\n" % self.name] +
            #["<p>%s days, %s tweets</p>\n" % (
            #        len(self.days), self.total_tweets)] +
            [day.in_story_timeline_html for day in self.days])

    @property
    def real_world_timeline_html(self):
        chapter_start_date = self.start_date.strftime(Tweet.REAL_WORLD_TIMELINE_DATE_FORMAT)
        if chapter_start_date != self.real_days[0].date:
            print '[WARNING] Chapter "%s" starts on %s, but its first tweet happens on %s' % (
                self.name, chapter_start_date, self.real_days[0].date)
        return "\n".join(
            ["<h2>%s</h2>\n" % self.name] +
            [day.real_world_timeline_html for day in self.real_days])


    @property
    def total_tweets(self):
        return sum(len(x.tweets) for x in self.days)

    @property
    def all_tweets(self):
        for d in self.days:
            for t in d.tweets:
                yield t

    @property
    def real_days(self):
        """A list of Day objects corresponding to real-world days for this chapter."""
        days = []
        current_date = None
        current_day = None
        for story_day in self.days:
            for tweet in story_day.tweets:
                if tweet.timestamp_date_str != current_date:
                    current_date = tweet.timestamp_date_str
                    current_day = Day(current_date)
                    days.append(current_day)
                current_day.tweets.append(tweet)
        return days


class Day:

    """A day's worth of tweets--either an in-story day or a real-world day."""

    def __init__(self, date):
        self.date = date
        self.tweets = []

    @property
    def in_story_timeline_html(self):
        if len(self.tweets) == 0:
            return ""
        return "\n".join(
            ["<h3>%s</h3>" % self.date, "<ul>"] +
            [tweet.in_story_timeline_html for tweet in self.tweets] + ["</ul>"])

    @property
    def real_world_timeline_html(self):
        if len(self.tweets) == 0:
            return ""
        return "\n".join(
            ["<h3>%s</h3>" % self.date, "<ul>"] +
            [tweet.real_world_timeline_html for tweet in self.tweets] + ["</ul>"])

class Tweet(TimezoneAware):

    REAL_WORLD_TIMELINE_TIME_FORMAT = "%H:%M"
    REAL_WORLD_TIMELINE_DATE_FORMAT = "%a %d %b"

    def __init__(self, text, author, base_timecode, timezone, delay=None,
                 hour_of_day=None, in_reply_to=None, progress=None):
        self.text = text
        self.author = author
        self.timezone = timezone
        self.in_reply_to = in_reply_to
        self.digest = hashlib.md5(self.text).hexdigest()
        self.delay = delay
        self.hour_of_day = hour_of_day
        if self.delay is None and self.hour_of_day is None:
            self.delay = DEFAULT_DELAY
        self.base_timecode = base_timecode

        # In general, timestamps are calculated in a second pass.
        self.timestamp = None

        # However, if this tweet has already been posted, we know its
        # timestamp already.
        if progress is not None:
            as_posted = progress.posts.get(self.digest)
            if as_posted is not None:
                self.timestamp = datetime.strptime(
                    as_posted['planned_timestamp'], JSON_TIME_FORMAT).replace(
                    tzinfo=pytz.timezone("UTC"))

        if (self.hour_of_day is not None and self.delay is not None
            and self.delay < timedelta(days=1)):
            raise ValueError(
                '"%s" defines both a delay and an hour of day, but the delay '
                'is less than one day.' % text)

    def calculate_timestamp(self, fuzz_quotient, fuzz_minimum_seconds,
                            previous_tweet):
        timestamp = self.base_timecode or previous_tweet.timestamp
        if self.timestamp is not None:
            # This tweet already has a timestamp, possibly because
            # it's already been posted. Leave it alone.
            return self.timestamp

        # If the delay after the last tweet is one day or more, apply
        # it before setting the time of day.
        one_day = timedelta(days=1)
        if self.delay is not None and self.delay >= one_day:
            timestamp += self.delay
            timestamp = self.start_of_day(timestamp)

        # If a time of day is given, set it now.
        if self.hour_of_day is not None:
            if timestamp.hour > self.hour_of_day:
                # Bump to the next real-world day.
                timestamp = timestamp + timedelta(days=1)
            timestamp = timestamp.replace(
                hour=self.hour_of_day, minute=0, second=0)

        # If the delay is less than one day, apply it now.
        if self.delay is not None and self.delay < one_day:
            timestamp += self.delay

        # Now we have a precise timestamp. But posting one tweet
        # exactly 30 minutes after another one will look fake. We need
        # to fudge the timestamp a little.

        if self.hour_of_day is not None:
            # We know which hour the tweet should go out. Pick
            # sometime in the first 45 minutes of that hour, to
            # minimize the chances of collisions with future tweets.
            actual_delta = timedelta(seconds=random.randint(0, 45*60))
            timestamp = timestamp + actual_delta
        elif self.delay is not None:
            # We know approximately how long after the previous tweet
            # this tweet should go out. Pick sometime
            delay_seconds = self.delay.seconds
            maximum_variation = max(
                delay_seconds * fuzz_quotient, fuzz_minimum_seconds)
            actual_variation = random.randint(-maximum_variation, maximum_variation)
            actual_delta = timedelta(seconds=actual_variation)
            if random.randint(0,1) == 1:
                timestamp = timestamp + actual_delta
            else:
                timestamp = timestamp - actual_delta
        else:
            raise ValueError(
                'Tweet "%s" has neither hour-of-day nor delay since previous '
                'tweet. Cannot calculate timestamp.' % self.text)
        return timestamp

    @property
    def json(self):
        if self.in_reply_to is None:
            in_reply_to = None
        else:
            in_reply_to = self.in_reply_to.digest
        d = dict(internal_id=self.digest, text=self.text,
                 author=self.author['account'],
                 in_reply_to=in_reply_to, timestamp=self.timestamp_for_json)
        return json.dumps(d)

    def li(self, text):
        a = []
        if self.in_reply_to is not None:
            a.append("<ul>")
        a.append('<li class="%s">%s</li>' % (self.author['css_class'], text))
        if self.in_reply_to is not None:
            a.append("</ul>")
        return "\n".join(a)

    @property
    def in_story_timeline_html(self):
        return self.li(self.text)

    @property
    def timestamp_str(self):
        return self.timestamp.strftime(self.REAL_WORLD_TIMELINE_TIME_FORMAT)

    @property
    def timestamp_for_json(self):
        return self.timestamp.astimezone(pytz.timezone("UTC")).strftime(
            JSON_TIME_FORMAT)

    @property
    def timestamp_date_str(self):
        return self.timestamp.strftime(self.REAL_WORLD_TIMELINE_DATE_FORMAT)

    @property
    def real_world_timeline_html(self):
        text = self.timestamp_str + " " + self.text
        return self.li(text)

class Stream:

    def __init__(self, lines, tweet_parser=None, config=None, progress=None):
        if tweet_parser is None:
            if config is None:
                raise ValueError(
                    "You tried to create a stream without providing a "
                    "tweet parser or a configuration for one.")
            tweet_parser = TweetParser(config=config, progress=progress)
        self.current_chapter = None
        self.current_day = None
        self.chapters = []
        self.tweet_parser = tweet_parser
        self.latest_tweet = None

        for line in lines:
            line = line.strip()
            if len(line) == 0:
                continue

            if line[:3] == "== ":
                self.end_chapter()
                self.begin_chapter(line[3:])
            elif line[:3] == "-- ":
                self.end_day()
                self.begin_day(line[3:])
            else:
                self.add_tweet(line)
        self.end_chapter()
        self.add_fuzz()
        self.chapter_start_sanity_check()

    def html_page(self, real_time=False):

        START = '''<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
'''

        l = [START]
        l.append('<style type="text/css">')
        for author in self.tweet_parser.authors:
              l.append(".%s { background-color: %s }" % (
                      author['css_class'], author['color']))
        l.append('</style></head><body>')

        l.append("<p>Author guide:</p>")
        l.append("<ul>")
        for author in self.tweet_parser.authors:
            l.append('<li class="%s">%s</a>' % (author['css_class'], author['account']))
        l.append("</ul>")
        if real_time:
            l.append(self.real_world_timeline_html)
        else:
            l.append(self.in_story_timeline_html)
        l.append("</body></html")
        return "\n".join(l)

    @property
    def in_story_timeline_html(self):
        return "\n\n".join(chapter.in_story_timeline_html for chapter in self.chapters)

    @property
    def real_world_timeline_html(self):
        return "\n\n".join(chapter.real_world_timeline_html for chapter in self.chapters)

    @property
    def tweets(self):
        for chapter in self.chapters:
            for day in chapter.days:
                for tweet in day.tweets:
                    yield tweet

    def add_tweet(self, line):
        if self.current_chapter is None:
            self.begin_chapter("")
        if self.current_day is None:
            self.begin_day("")

        line = line.strip()
        tweet = self.tweet_parser.parse(line, self)
        self.current_day.tweets.append(tweet)
        self.latest_tweet = tweet
        return tweet

    def end_chapter(self):
        if self.current_chapter is None:
            # No current chapter.
            return

        self.end_day()
        self.current_chapter = None

    def begin_chapter(self, chapter_name):
        if len(self.chapters) == 0:
            start_date = self.tweet_parser.start_of_day(
                self.tweet_parser.config['start_date'])
        else:
            previous_chapter = self.chapters[-1]
            duration = self.tweet_parser.config['chapter_duration_days']
            start_date = previous_chapter.start_date + duration
        self.current_chapter = Chapter(chapter_name, start_date)
        self.chapters.append(self.current_chapter)

    def end_day(self):
        if self.current_day is None:
            return
        self.current_day = None

    def begin_day(self, date):
        self.current_day = Day(date)
        self.current_chapter.days.append(self.current_day)


    def add_fuzz(self):
        previous_tweet = None
        for tweet in self.tweets:
            progress = self.tweet_parser.progress
            if (progress is not None
                and progress.posts.get(tweet.digest) is not None):
                # This tweet has already been posted. Don't mess with it.
                previous_tweet = tweet
                continue
            success = False
            for i in range(0, 10):
                tweet.timestamp = tweet.calculate_timestamp(
                    self.tweet_parser.fuzz_quotient,
                    self.tweet_parser.fuzz_minimum_seconds,
                    previous_tweet)
                if (previous_tweet is None
                    or previous_tweet.timestamp < tweet.timestamp):
                    # This timestamp is fine. Stop trying to calculate it.
                    success = True
                    break
                # If we didn't break, the timestamp we calculated came
                # before previous tweet's timestamp, which is a
                # problem. Restart the loop and calculate a different
                # timestamp.
            if not success:
                # We tried to calculate the timestamp ten times with
                # no success. Raise an error.
                raise ValueError('Calculated timestamp for "%s" is %s, which comes before calculated timestamp for the previous tweet "%s" (%s). Trying again may help.' % (
                        tweet.text, tweet.timestamp_str, previous_tweet.text, previous_tweet.timestamp_str))
            previous_tweet = tweet

    def chapter_start_sanity_check(self):
        previous_chapter = self.chapters[0]
        for chapter in self.chapters[1:]:
            tweets = list(previous_chapter.all_tweets)
            if len(tweets) > 0:
                previous_chapter_last_tweet = tweets[-1]
                if previous_chapter_last_tweet.timestamp > chapter.start_date:
                    print '[WARNING] Last tweet in chapter "%s" overlaps the start of chapter "%s"' % (
                        previous_chapter.name, chapter.name)
            previous_chapter = chapter

    @property
    def json(self):
        return "\n".join(tweet.json for tweet in self.tweets)
