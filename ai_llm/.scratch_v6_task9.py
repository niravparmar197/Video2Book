import os

os.environ["VIDEO_MODE"] = "captions_only"
os.environ["BOOK_ORDER"] = "video"
os.environ["VOLUME_HOURS"] = "0.2"  # force a real split across the 3-video playlist

from unittest.mock import patch

from app.youtube import PlaylistEntry
from app import graph as graph_module

entries = [
    PlaylistEntry(
        video_id="aircAruvnKk",
        title="But what is a neural network?",
        url="https://www.youtube.com/watch?v=aircAruvnKk",
        playlist_index=1,
    ),
    PlaylistEntry(
        video_id="IHZwWFHWa-w",
        title="Gradient descent, how neural networks learn",
        url="https://www.youtube.com/watch?v=IHZwWFHWa-w",
        playlist_index=2,
    ),
    PlaylistEntry(
        video_id="Ilg3gGewQ5U",
        title="Backpropagation, intuitively",
        url="https://www.youtube.com/watch?v=Ilg3gGewQ5U",
        playlist_index=3,
    ),
]

OUT = (
    r"C:\Users\asus\AppData\Local\Temp\claude\F--morden-system-desing-Video2Book-ai-llm"
    r"\ac7f66a9-b3ad-4ab6-bd75-5b5613f5dd74\scratchpad\v6task9_verify"
)

with patch("app.nodes.fetch.list_playlist_videos", return_value=entries):
    pdf_path = graph_module.run_book(
        "https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",
        OUT,
    )
print("PDF_PATH:", pdf_path, pdf_path.exists())
