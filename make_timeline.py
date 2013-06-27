from timeline import load_stream, Stream
import os
import sys

if len(sys.argv) != 2:
    print "Usage: %s [script directory]" % sys.argv[0]
    sys.exit()

script_directory = sys.argv[1]
stream = load_stream(script_directory)

timeline_filename = os.path.join(script_directory, "timeline.html")
print "Writing HTML timeline to %s." % timeline_filename
open(timeline_filename, "w").write(stream.html_page(real_time=True))

json_script_filename = os.path.join(script_directory, "timeline.json")
print "Writing JSON timeline to %s." % json_script_filename
open(json_script_filename, "w").write(stream.json)
