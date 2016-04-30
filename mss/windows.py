#!/usr/bin/env python
# coding: utf-8
''' This is part of the MSS Python's module.
    Source: https://github.com/BoboTiG/python-mss
'''

from ctypes import (
    POINTER, WINFUNCTYPE, Structure, c_void_p, create_string_buffer, sizeof,
    windll)
from ctypes.wintypes import (
    BOOL, DOUBLE, DWORD, HBITMAP, HDC, HGDIOBJ, HWND, INT, LONG, LPARAM, RECT,
    UINT, WORD)

from .base import MSSBase
from .exception import ScreenshotError

__all__ = ['MSS']


class BITMAPINFOHEADER(Structure):
    ''' Information about the dimensions and color format of a DIB. '''

    _fields_ = [('biSize', DWORD), ('biWidth', LONG), ('biHeight', LONG),
                ('biPlanes', WORD), ('biBitCount', WORD),
                ('biCompression', DWORD), ('biSizeImage', DWORD),
                ('biXPelsPerMeter', LONG), ('biYPelsPerMeter', LONG),
                ('biClrUsed', DWORD), ('biClrImportant', DWORD)]


class BITMAPINFO(Structure):
    ''' Structure that the dimensions and color information for a DIB. '''

    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', DWORD * 3)]


class MSS(MSSBase):
    ''' Mutliple ScreenShots implementation for Microsoft Windows. '''

    def __init__(self):
        ''' Windows initialisations. '''

        self.monitorenumproc = WINFUNCTYPE(INT, DWORD, DWORD, POINTER(RECT),
                                           DOUBLE)
        set_argtypes(self.monitorenumproc)
        set_restypes()

    def enum_display_monitors(self, force=False):
        ''' Get positions of monitors (see parent class). '''

        if not self.monitors or force:
            # All monitors
            sm_xvirtualscreen, sm_yvirtualscreen = 76, 77
            sm_cxvirtualscreen, sm_cyvirtualscreen = 78, 79
            left = windll.user32.GetSystemMetrics(sm_xvirtualscreen)
            right = windll.user32.GetSystemMetrics(sm_cxvirtualscreen)
            top = windll.user32.GetSystemMetrics(sm_yvirtualscreen)
            bottom = windll.user32.GetSystemMetrics(sm_cyvirtualscreen)
            self.monitors.append({
                b'left': int(left),
                b'top': int(top),
                b'width': int(right - left),
                b'height': int(bottom - top)
            })

            # Each monitors
            def _callback(monitor, data, rect, dc_):
                ''' Callback for monitorenumproc() function, it will return
                    a RECT with appropriate values.
                '''

                del monitor, data, dc_
                rct = rect.contents
                self.monitors.append({
                    b'left': int(rct.left),
                    b'top': int(rct.top),
                    b'width': int(rct.right - rct.left),
                    b'height': int(rct.bottom - rct.top)
                })
                return 1

            callback = self.monitorenumproc(_callback)
            windll.user32.EnumDisplayMonitors(0, 0, callback, 0)

        return self.monitors

    def get_pixels(self, monitor):
        ''' Retrieve all pixels from a monitor. Pixels have to be RGB.

            In the code, there are few interesting things:

            [1] bmi.bmiHeader.biHeight = -height

            A bottom-up DIB is specified by setting the height to a
            positive number, while a top-down DIB is specified by
            setting the height to a negative number.
            https://msdn.microsoft.com/en-us/library/ms787796.aspx
            https://msdn.microsoft.com/en-us/library/dd144879%28v=vs.85%29.aspx


            [2] bmi.bmiHeader.biBitCount = 32
                image_data = create_string_buffer(height * width * 4)
                # and later, the BGRX to RGB conversion

            We grab the image in RGBX mode, so that each word is 32bit
            and we have no striding, then we transform to RGB.
            Inspired by https://github.com/zoofIO/flexx


            [3] bmi.bmiHeader.biClrUsed = 0
                bmi.bmiHeader.biClrImportant = 0

            When biClrUsed and biClrImportant are set to zero, there
            is "no" color table, so we can read the pixels of the bitmap
            retrieved by gdi32.GetDIBits() as a sequence of RGB values.
            Thanks to http://stackoverflow.com/a/3688682
        '''

        width, height = monitor[b'width'], monitor[b'height']
        left, top = monitor[b'left'], monitor[b'top']
        srcdc = None
        memdc = None
        bmp = None

        try:
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # Why minux? See [1]
            bmi.bmiHeader.biPlanes = 1  # Always 1
            bmi.bmiHeader.biBitCount = 32  # See [2]
            bmi.bmiHeader.biCompression = 0  # 0 = BI_RGB (no compression)
            bmi.bmiHeader.biClrUsed = 0  # See [3]
            bmi.bmiHeader.biClrImportant = 0  # See [3]

            image_data = create_string_buffer(height * width * 4)  # See [2]
            srcdc = windll.user32.GetWindowDC(0)
            memdc = windll.gdi32.CreateCompatibleDC(srcdc)
            bmp = windll.gdi32.CreateCompatibleBitmap(srcdc, width, height)
            windll.gdi32.SelectObject(memdc, bmp)
            windll.gdi32.BitBlt(memdc, 0, 0, width, height, srcdc, left, top,
                                0xCC0020)  # 0xCC0020 = SRCCOPY
            bits = windll.gdi32.GetDIBits(memdc, bmp, 0, height, image_data,
                                          bmi, 0)  # 0 = DIB_RGB_COLORS
            if bits != height:
                raise ScreenshotError('gdi32.GetDIBits() failed.')
        finally:
            # Clean up
            if srcdc:
                windll.gdi32.DeleteObject(srcdc)
            if memdc:
                windll.gdi32.DeleteObject(memdc)
            if bmp:
                windll.gdi32.DeleteObject(bmp)

        # Replace pixels values: BGRX to RGB. See [2].
        image = bytearray(height * width * 3)
        image[0::3], image[1::3], image[2::3] = \
            image_data[2::4], image_data[1::4], image_data[0::4]
        self.image = bytes(image)
        return self.image


def set_argtypes(callback):
    ''' Functions arguments. '''

    windll.user32.GetSystemMetrics.argtypes = [INT]
    windll.user32.EnumDisplayMonitors.argtypes = \
        [HDC, c_void_p, callback, LPARAM]
    windll.user32.GetWindowDC.argtypes = [HWND]
    windll.gdi32.CreateCompatibleDC.argtypes = [HDC]
    windll.gdi32.CreateCompatibleBitmap.argtypes = [HDC, INT, INT]
    windll.gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
    windll.gdi32.BitBlt.argtypes = \
        [HDC, INT, INT, INT, INT, HDC, INT, INT, DWORD]
    windll.gdi32.DeleteObject.argtypes = [HGDIOBJ]
    windll.gdi32.GetDIBits.argtypes = \
        [HDC, HBITMAP, UINT, UINT, c_void_p, POINTER(BITMAPINFO), UINT]


def set_restypes():
    ''' Functions return type. '''

    windll.user32.GetSystemMetrics.restypes = INT
    windll.user32.EnumDisplayMonitors.restypes = BOOL
    windll.user32.GetWindowDC.restypes = HDC
    windll.gdi32.CreateCompatibleDC.restypes = HDC
    windll.gdi32.CreateCompatibleBitmap.restypes = HBITMAP
    windll.gdi32.SelectObject.restypes = HGDIOBJ
    windll.gdi32.BitBlt.restypes = BOOL
    windll.gdi32.GetDIBits.restypes = INT
    windll.gdi32.DeleteObject.restypes = BOOL
