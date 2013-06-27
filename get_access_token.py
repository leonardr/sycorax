# Get a Twitter access token for use with Sycorax

from oauth.oauth import (
    OAuthConsumer, OAuthRequest, OAuthToken,
    OAuthSignatureMethod_HMAC_SHA1 as HMAC)
from twitter import ACCESS_TOKEN_URL, AUTHORIZATION_URL, REQUEST_TOKEN_URL
from keys import TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET
from httplib2 import Http
import json
import sys
import urlparse

consumer = OAuthConsumer(TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET)

def get_request_token():

    oauth_request = OAuthRequest.from_consumer_and_token(
        consumer, http_method="POST", http_url=REQUEST_TOKEN_URL,
        callback="oob")

    oauth_request.sign_request(HMAC(), consumer, "")
    headers = oauth_request.to_header()

    client = Http()
    response, body = client.request(REQUEST_TOKEN_URL, "POST", headers=headers)
    token = OAuthToken.from_string(body)
    return token

def exchange_pin_for_access_token(pin, request_token):

    parameters=dict(oauth_verifier=pin)
    oauth_request = OAuthRequest.from_consumer_and_token(
        consumer, request_token, http_method="POST", http_url=ACCESS_TOKEN_URL,
        parameters=parameters)
    oauth_request.sign_request(HMAC(), consumer, request_token)
    headers = oauth_request.to_header()

    client = Http()
    response, body = client.request(ACCESS_TOKEN_URL, "POST", headers=headers)
    token = OAuthToken.from_string(body)
    return token, body


def main():
    print "Let's set up a character with Sycorax!"
    print
    token = get_request_token()
    url = AUTHORIZATION_URL + "?oauth_token=%s" % token.key
    print "1. Log in to Twitter as your character."
    print "2. Visit this URL: %s" % url
    print "3. Authorize Sycorax to access your character's account."
    print "4. Come back here, type in the PIN you got from Twitter, and hit Enter: "
    pin = int(sys.stdin.readline().strip())
    token, body = exchange_pin_for_access_token(pin, token)
    screen_name = urlparse.parse_qs(body)['screen_name'][0]
    output = dict(
        account=screen_name, twitter_token=token.key,
        twitter_secret=token.secret)
    print
    print "Success!"
    print 'Put something like this as your "authors" list in config.json:'
    print json.dumps([output])


if __name__ == '__main__':
    main()

