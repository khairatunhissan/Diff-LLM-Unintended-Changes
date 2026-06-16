diff --git a/mps_youtube/commands/local_playlist.py b/mps_youtube/commands/local_playlist.py
index 681a1d7..41cf4ae 100644
--- a/mps_youtube/commands/local_playlist.py
+++ b/mps_youtube/commands/local_playlist.py
@@ -29,9 +29,11 @@ def playlist_remove(name):
 def playlist_add(nums, playlist):
     """ Add selected song nums to saved playlist. """
     nums = util.parse_multi(nums)
+    # Replacing spaces with hyphens before checking if playlist already exist.
+    # See https://github.com/mps-youtube/mps-youtube/issues/1046.
+    playlist = playlist.replace(" ", "-")
 
     if not g.userpl.get(playlist):
-        playlist = playlist.replace(" ", "-")
         g.userpl[playlist] = Playlist(playlist)
 
     for songnum in nums:
