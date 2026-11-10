from base64 import b64encode
from io import BytesIO
from pathlib import Path

from PIL import Image
from PIL.ImageFile import ImageFile


class Screenshot(Path):
    def __init__(self, *args):
        super().__init__(*args)

        self.width, self.height = self.image.size

        self._base64 = None

    @property
    def base64(self) -> str:
        if self._base64 is None:
            bio = BytesIO()

            with self.image as image:
                image.save(bio, format='PNG')

            self._base64 = b64encode(bio.getvalue()).decode('utf-8')
        return self._base64

    @property
    def image(self) -> ImageFile:
        return Image.open(self)
