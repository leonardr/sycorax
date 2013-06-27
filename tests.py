"""Unit tests."""

from datetime import datetime, timedelta
from unittest import main, TestCase
from timeline import TweetParser, Stream, Tweet, Day, Chapter
import pytz

# Begin mock objects.

class SycoraxTestCase(TestCase):

    AUTHORS = [
        dict(account="author1",
             code="",
             css_class="a1",
             color="red",
             ),

        dict(account="author2",
             code="+",
             css_class="a2",
             color="green",
             ),

        dict(account="author3",
             code="-",
             css_class="a3",
             color="blue",
             ),
        ]

    TIMEZONE = "US/Central"
    TIMEZONE_O = pytz.timezone(TIMEZONE)

    START_DATE = datetime(2000, 1, 1, 0, 0, 0, tzinfo=TIMEZONE_O)

    CONFIG = dict(authors=AUTHORS, timezone=TIMEZONE,
                  start_date=START_DATE, CHAPTER_DURATION=10)

    UID = 0

    @property
    def uid(self):
        v = str(self.UID)
        self.UID += 1
        return v

    def make_tweet(self, text=None, author=None, base_timecode=None,
                   timezone=None, delay=None, hour_of_day=None,
                   in_reply_to=None):
        text = text or self.uid
        author = author or self.AUTHORS[0]
        timezone = timezone or self.TIMEZONE
        base_timecode = base_timecode or self.START_DATE
        return Tweet(
            text, author, base_timecode, timezone, delay, hour_of_day,
            in_reply_to)

    def make_day(self, date=None, tweets=None):
        date = date or self.START_DATE
        return Day(date)

    def make_chapter(self, start_date=None):
        start_date = start_date or self.START_DATE
        return Chapter(start_date)

    def make_parser(self, config={}, fuzz_quotient=0, fuzz_minimum_seconds=0):
        base_config = dict(self.CONFIG)
        base_config.update(config)
        return TweetParser(base_config, fuzz_quotient, fuzz_minimum_seconds)

    def make_stream(self, tweet_parser=None, *lines):
        tweet_parser = tweet_parser or self.make_parser()
        return Stream(lines, tweet_parser)

    def assertDefaultAuthor(self, tweet):
        """Assert that the given tweet has the default author."""
        self.assertEquals(self.AUTHORS[0]['account'], tweet.author['account'])

    def assertDelayEquals(self, tweet, **kwargs):
        delay = timedelta(**kwargs)
        self.assertEquals(tweet.delay, delay)

class TestTweetParser(SycoraxTestCase):

    def tweet_for(self, line):
        stream = self.make_stream(None, line)
        return stream.latest_tweet

    def test_single_word_tweet(self):
        tweet = self.tweet_for("Foobar")
        self.assertEquals("Foobar", tweet.text)
        self.assertDefaultAuthor(tweet)

    def test_no_command(self):
        tweet = self.tweet_for("foo bar baz")
        self.assertEquals("foo bar baz", tweet.text)

    def test_tweet_that_looks_like_a_command_but_isnt(self):
        text = "Rh+ blood type"
        tweet = self.tweet_for(text)
        self.assertEquals(text, tweet.text)
        self.assertDefaultAuthor(tweet)

    def test_alternate_author(self):
        tweet = self.tweet_for("+ Foobar")
        self.assertEquals("Foobar", tweet.text)
        self.assertEquals(self.AUTHORS[1], tweet.author)

    def test_reply_to(self):
        stream = self.make_stream()
        t1 = stream.add_tweet("Original text")
        t2 = stream.add_tweet("R+ A reply")

        self.assertEquals(t2.in_reply_to, t1)

    def test_first_tweet_cannot_be_reply(self):
        self.assertRaises(ValueError, self.tweet_for, "R A reply")

    def test_delay_minutes(self):
        tweet = self.tweet_for("40M Foobar")
        self.assertEquals("Foobar", tweet.text)
        self.assertDelayEquals(tweet, minutes=40)

    def test_delay_days(self):
        tweet = self.tweet_for("2D Foobar")
        self.assertEquals("Foobar", tweet.text)
        self.assertDelayEquals(tweet, days=2)

    def test_hour_of_day_am(self):
        tweet = self.tweet_for("10A Foobar")
        self.assertEquals(10, tweet.hour_of_day)

    def test_hour_of_day_noon(self):
        tweet = self.tweet_for("12P Foobar")
        self.assertEquals(12, tweet.hour_of_day)

    def test_hour_of_day_pm(self):
        tweet = self.tweet_for("1P Foobar")
        self.assertEquals(13, tweet.hour_of_day)

    def test_hour_of_day_midnight(self):
        tweet = self.tweet_for("12A Foobar")
        self.assertEquals(0, tweet.hour_of_day)

    def test_multi_day_delay_plus_time_of_day(self):
        tweet = self.tweet_for("2D9A Foobar")
        self.assertDelayEquals(tweet, days=2)
        self.assertEquals(tweet.hour_of_day, 9)

    def test_less_than_day_delay_plus_time_of_day_fails(self):
        self.assertRaises(ValueError, self.tweet_for, "1H9A Foobar")

    def test_bad_time_of_day_fails(self):
        text = "13P Foobar"
        self.assertRaises(ValueError, self.tweet_for, text)

class TestTimecodeAssignment(SycoraxTestCase):

    def tweet_for(self, text=None, author=None, base_timecode=None,
              delay=None, hour_of_day=None, reply_to=None):

        tweet = self.make_tweet(
            text, author, base_timecode, self.TIMEZONE_O, delay, hour_of_day,
            reply_to)
        tweet.timestamp = tweet.calculate_timestamp(0, 0, None)
        return tweet

    def test_hour_of_day(self):
        tweet = self.tweet_for(hour_of_day=15)
        self.assertEquals(15, tweet.timestamp.hour)

    def test_long_delay_plus_hour_of_day(self):
        tweet = self.tweet_for(delay=timedelta(days=2), hour_of_day=5)
        self.assertEquals(tweet.timestamp.day, 3)
        self.assertEquals(tweet.timestamp.hour, 5)

    def test_hour_of_day_before_base_timecode_pushes_tweet_to_next_day(self):
        base = self.START_DATE.replace(hour=15)
        tweet = self.tweet_for(
            hour_of_day=10,
            base_timecode=base)
        self.assertEquals(tweet.timestamp.hour, 10)
        self.assertEquals(tweet.timestamp.day, base.day+1)

    def test_fuzz_on_relative_delay(self):
        parser = self.make_parser(fuzz_quotient=0.5)
        stream = self.make_stream(parser, "First tweet", "10M Second tweet")
        t1, t2 = stream.tweets
        self.assertEquals(self.START_DATE, t1.timestamp)

        # The second tweet's timestamp will not be precisely 10
        # minutes after the first, but it will be within 10 minutes,
        # plus or minus 50%.
        self.assertTrue(t2.timestamp-t1.timestamp < timedelta(minutes=15))

    def test_deterministic_tweets(self):
        parser = self.make_parser(fuzz_quotient=0, fuzz_minimum_seconds=0)
        stream = self.make_stream(parser, "First tweet", "1M Second tweet")
        t1, t2 = stream.tweets

        # The fuzz quotient and fuzz minimum seconds are zero, so the
        # timestamps are perfectly deterministic.
        self.assertEquals(t1.timestamp, self.START_DATE)
        self.assertEquals(t2.timestamp - t1.timestamp, timedelta(minutes=1))

    def test_minimum_fuzz_seconds(self):
        parser = self.make_parser(fuzz_quotient=0, fuzz_minimum_seconds=60)
        stream = self.make_stream(parser, "First tweet")
        [t1] = stream.tweets

        # The fuzz quotient is zero, so timestamps would be
        # deterministic, but there's a minimum of 60 seconds worth of
        # fuzz, so the first timestamp will be up to one minute off
        # from START_DATE.

        # This test will fail one time in 60, but we need to test that
        # *some* fuzz is being applied.
        self.assertTrue(t1.timestamp != self.START_DATE)
        difference = abs((t1.timestamp - self.START_DATE).seconds)
        self.assertTrue(difference < 60)

    def test_fuzz_on_hour_of_day(self):
        # A tweet that takes place in the ten o'clock hour will
        # take place sometime in the first 45 minutes of that hour.
        tweet = self.tweet_for(hour_of_day=10)

        # This will fail one time in 60, but it's important to check that
        # *some* fuzz is being applied.
        self.assertNotEquals(tweet.timestamp.minute, 0)
        self.assertTrue(tweet.timestamp.minute <= 45)

if __name__ == '__main__':
    main()
