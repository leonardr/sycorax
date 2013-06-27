"""Publish timelines to Twitter."""

from datetime import datetime, timedelta
from parsedatetime.parsedatetime import Calendar
import os
import json
import sys

import twitter

from timeline import load_config, JSON_TIME_FORMAT

from keys import TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET

# This is a safety mechanism that prevents tweets that you modified by
# accident from being double-posted. If Sycorax stops running for some
# reason, this may also give you the opportunity to catch up on the
# tweets that were missed, rather than having an old tweet posted
# every time Sycorax runs.
DONT_POST_TWEETS_OLDER_THAN = timedelta(days=2)

TWITTER_TIME_FORMAT = "%a %b %d %H:%M:%S +0000 %Y"

class Story(object):

    def __init__(self, config, script_filehandle, progress_filename):
        self.progress_filename = progress_filename

        self.script = [json.loads(line.strip()) for line in script_filehandle]
        if os.path.exists(progress_filename):
            self.progress = [json.loads(line.strip())
                             for line in open(progress_filename)]
        else:
            # No progress yet
            self.progress = []
        self.credentials_by_account = {}
        for author in config['authors']:
            self.credentials_by_account[author['account']] = (
                author['twitter_token'], author['twitter_secret'])

        self.posted_tweets_by_internal_id = {}
        for posted_tweet in self.progress:
            self.posted_tweets_by_internal_id[posted_tweet['internal_id']] = (
                posted_tweet)

    def sync(self):
        """Synchronize by posting at most one tweet."""
        for tweet in self.script:
            if tweet['internal_id'] in self.posted_tweets_by_internal_id:
                # We already posted this tweet.
                continue
            else:
                # We have not yet posted this tweet.
                post_at = datetime.strptime(
                    tweet['timestamp'], JSON_TIME_FORMAT)
                now = datetime.utcnow()
                if post_at <= now:
                    if False and now - post_at > DONT_POST_TWEETS_OLDER_THAN:
                        print (
                            'Not posting "%s". It\'s so old (%s) that posting '
                            'it might screw up the timeline.' % (
                                tweet['text'], now-post_at))
                        continue
                    # It's time to post this sucker.
                    self.post(tweet)
                    continue
                else:
                    # This tweet's time has yet to come. Since the
                    # script is in chronological order, there's no
                    # point in looking further in the script.
                    print 'Coming up in %s: "%s"' % (post_at-now, tweet['text'])
                    pass
                break

    def post(self, tweet):
        text = tweet['text']
        print 'Posting "%s"' % text
        author_account = tweet['author']
        in_reply_to_id = tweet['in_reply_to']
        in_reply_to_twitter_id = None
        if in_reply_to_id is not None:
            # Find the actual Twitter ID of the tweet to which this is
            # a reply.
            in_reply_to = self.posted_tweets_by_internal_id.get(in_reply_to_id)
            if in_reply_to is None:
                print '"%s" is supposedly a response to nonexistent internal ID %s. Posting it as a standalone tweet instead.' % (text, in_reply_to_id)
            else:
                in_reply_to_twitter_id = in_reply_to['twitter_id']

        access_token_key, access_token_secret = self.credentials_by_account[
            author_account]
        oauth = twitter.OAuth(access_token_key, access_token_secret,
                              TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET)
        api = twitter.Twitter(auth=oauth)

        # Post the tweet.
        try:
            data = api.statuses.update(status=text, in_reply_to_status_id=in_reply_to_twitter_id)
            actual_time = datetime.strptime(data['created_at'], TWITTER_TIME_FORMAT)
            twitter_id = data['id']
            pass
        except twitter.TwitterError, e:
            if e.message != "Status is a duplicate.":
                raise e
            actual_time = datetime.now()
            twitter_id = '[duplicate]'
        #actual_time = datetime.now()
        #twitter_id = 120943957396785

        # Append to the log of progress
        progress_entry = dict(
            text=text,
            planned_timestamp=tweet['timestamp'],
            actual_timestamp=actual_time.strftime(JSON_TIME_FORMAT),
            internal_id=tweet['internal_id'],
            twitter_id=twitter_id)
        self.progress.append(progress_entry)

        self.save_progress(progress_entry)

    def save_progress(self, entry):
        handle = open(self.progress_filename, "a")
        handle.write(json.dumps(entry))
        handle.write("\n")
        handle.close()

if len(sys.argv) != 2:
    print "Usage: %s [script directory]" % sys.argv[0]
    sys.exit()

script_directory = sys.argv[1]
config = load_config(script_directory)

script_filename = os.path.join(script_directory, "timeline.json")
if not os.path.exists(script_filename):
    raise Exception(
        "Could not find timeline.json file in directory %s. "
        "Did you run make_timeline.py?" % script_directory)

progress_filename = os.path.join(script_directory, "progress.json")

story = Story(config, open(script_filename), progress_filename)
story.sync()
