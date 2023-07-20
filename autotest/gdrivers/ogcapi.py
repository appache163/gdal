#!/usr/bin/env pytest
# -*- coding: utf-8 -*-
###############################################################################
# $Id$
#
# Project:  GDAL/OGR Test Suite
# Purpose:  OGCAPI driver testing.
# Author:   Alessandro Pasotti <elpaso at itopen dot it>
#
###############################################################################
# Copyright (c) 2023, Alessandro Pasotti <elpaso at itopen dot it>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
###############################################################################

import os
import re
from http.server import BaseHTTPRequestHandler
from tempfile import TemporaryDirectory

import gdaltest
import ogrtest
import pytest
import webserver

from osgeo import gdal

# Source of test data
TEST_DATA_SOURCE_ENDPOINT = "https://maps.gnosis.earth/ogcapi"

# The following RECORD options control the download of test data when developing or debugging
# this test.
# Set RECORD to TRUE to recreate test data from the https://maps.gnosis.earth/ogcapi server
RECORD = False
# When RECORD is True, RECORD_NEW_ONLY will only download test data if they do not already
# exist in the test data directory.
# Note: when RECORD is TRUE and RECORD_NEW_ONLY is False control image are also regenerated
# making the test always pass.
RECORD_NEW_ONLY = True

BASE_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "ogcapi")

REPLACE_PORT_RE = re.compile(rb"http://127.0.0.1:\d{4}")
REPLACE_PRECISION_RE = re.compile(r"(\d+\.\d{4})\d+")


if RECORD:
    import shutil
    import urllib

    import requests

    ENDPOINT_PATH = urllib.parse.urlsplit(TEST_DATA_SOURCE_ENDPOINT).path


def sanitize_url(url):
    chars = "&#/?=:,()"
    text = url
    for c in chars:
        text = text.replace(c, "_")
    text = REPLACE_PRECISION_RE.sub("\\1", text)
    return text.replace("_fakeogcapi", "request")


class OGCAPIHTTPHandler(BaseHTTPRequestHandler):
    def log_request(self, code="-", size="-"):
        pass

    def do_GET(self):

        try:

            request_data_path = os.path.join(
                BASE_TEST_DATA_PATH, sanitize_url(self.path) + ".http_data"
            )

            is_fake = self.path.find("/fakeogcapi") != -1

            if is_fake and RECORD:

                if RECORD_NEW_ONLY and os.path.exists(request_data_path):
                    with open(request_data_path, "rb") as fd:
                        data = fd.read()
                else:
                    with open(request_data_path, "wb+") as fd:

                        response = requests.get(
                            TEST_DATA_SOURCE_ENDPOINT
                            + self.path.replace("/fakeogcapi", ""),
                            stream=True,
                        )
                        local_uri = (
                            "http://"
                            + self.address_string()
                            + ":"
                            + str(self.server.server_port)
                            + "/fakeogcapi"
                        ).encode("utf8")
                        content = response.content.replace(
                            TEST_DATA_SOURCE_ENDPOINT.encode("utf8"), local_uri
                        )
                        content = content.replace(
                            ENDPOINT_PATH.encode("utf8"), local_uri
                        )
                        data = b"HTTP/1.1 %s %s\r\n" % (
                            str(response.status_code).encode("utf8"),
                            response.reason.encode("utf8"),
                        )
                        for k, v in response.headers.items():
                            if k == "Content-Encoding":
                                continue
                            if k == "Content-Length":
                                data += (
                                    k.encode("utf8")
                                    + b": "
                                    + str(len(content)).encode("utf8")
                                    + b"\r\n"
                                )
                            else:
                                data += (
                                    k.encode("utf8")
                                    + b": "
                                    + v.encode("utf8")
                                    + b"\r\n"
                                )
                        data += b"\r\n"
                        data += content
                        fd.write(data)

                self.wfile.write(data)
                return

            elif self.path.find("/fakeogcapi") != -1:

                with open(request_data_path, "rb+") as fd:
                    response = REPLACE_PORT_RE.sub(
                        (
                            "http://"
                            + self.address_string()
                            + ":"
                            + str(self.server.server_port)
                        ).encode("utf8"),
                        fd.read(),
                    )
                    self.wfile.write(response)
                return

        except IOError:
            pass

        self.send_error(
            404,
            "File Not Found: %s" % self.path,
            "The requested URL was not found on this server.",
        )


###############################################################################
# Test underlying OGR drivers
#


pytestmark = pytest.mark.require_driver("OGCAPI")


###############################################################################
# Init
#


@pytest.fixture(scope="module", autouse=True)
def init():

    (gdaltest.webserver_process, gdaltest.webserver_port) = webserver.launch(
        handler=OGCAPIHTTPHandler
    )
    if gdaltest.webserver_port == 0:
        pytest.skip()
    yield

    webserver.server_stop(gdaltest.webserver_process, gdaltest.webserver_port)


def test_ogr_ogcapi_features():

    ds = gdal.OpenEx(
        "OGCAPI:http://127.0.0.1:%d/fakeogcapi" % gdaltest.webserver_port,
        gdal.OF_VECTOR,
        open_options=["CACHE=NO", "API=ITEMS"],
    )

    assert ds is not None

    sub_ds_uri = [
        v[0] for v in ds.GetSubDatasets() if v[1] == "Collection ne_10m_lakes_europe"
    ][0]

    del ds

    ds = gdal.OpenEx(sub_ds_uri, gdal.OF_VECTOR, open_options=["CACHE=NO", "API=ITEMS"])
    assert ds is not None

    lyr = ds.GetLayerByName("NaturalEarth:physical:ne_10m_lakes_europe")
    assert lyr is not None

    feat = lyr.GetNextFeature()
    fdef = feat.GetDefnRef()
    assert fdef.GetFieldDefn(0).GetName() == "feature::id"
    assert fdef.GetFieldDefn(3).GetName() == "name"

    ogrtest.check_feature_geometry(
        feat,
        "POLYGON ((-4.6543673319905 58.1553000824025,-4.6250972807178 58.1436693142282,-4.6081017670756 58.1342702801685,-4.5893036989562 58.1245279023988,-4.5722223493866 58.1163305713239,-4.5518792345724 58.1083907480315,-4.5339395257279 58.101137612159,-4.5218366599524 58.0922965116279,-4.4935108038821 58.0780048297015,-4.4530820820363 58.0534128364768,-4.4285330067753 58.0354731276323,-4.4254429133858 58.0470180598791,-4.4260437648782 58.0616530855155,-4.4324814594397 58.0646573429775,-4.4707642830983 58.0880047152536,-4.5038969511079 58.1081761582128,-4.5227808551547 58.1120816929134,-4.5409780717817 58.1248712461088,-4.5504200238052 58.126330456876,-4.563467084783 58.126330456876,-4.5802050906427 58.14002128731,-4.6111918604651 58.154055461454,-4.6317924830617 58.1573601446622,-4.6504188793261 58.1622527925289,-4.6814056491485 58.1725960217909,-4.7105898644937 58.182252563633,-4.7324780260026 58.1904928126717,-4.7421774858085 58.1910936641641,-4.7303321278154 58.179591649881,-4.6950535616188 58.1656003937008,-4.6762554934994 58.1598064685955,-4.6543673319905 58.1553000824025))",
        max_error=0.00001,
    )
    assert feat.GetField("name") == "Loch Bhanabhaidh"
    assert feat.GetField("feature::id") == 1
    assert feat.GetField("id") == 98696

    del lyr
    del ds


@pytest.mark.parametrize(
    "vector_format",
    (
        "AUTO",
        "GEOJSON",
        "GEOJSON_PREFERRED",
        "MVT",
        "MVT_PREFERRED",
    ),
)
def test_ogr_ogcapi_vector_tiles(vector_format):

    ds = gdal.OpenEx(
        "OGCAPI:http://127.0.0.1:%d/fakeogcapi" % gdaltest.webserver_port,
        gdal.OF_VECTOR,
        open_options=["CACHE=NO", "API=TILES", f"VECTOR_FORMAT={vector_format}"],
    )

    assert ds is not None

    sub_ds_uri = [
        v[0] for v in ds.GetSubDatasets() if v[1] == "Collection ne_10m_lakes_europe"
    ][0]

    del ds

    # Remove the format specifier from the URL so we can test the formats
    sub_ds_uri = sub_ds_uri.replace("?f=json", "")
    ds = gdal.OpenEx(
        sub_ds_uri,
        gdal.OF_VECTOR,
        open_options=["CACHE=NO", "API=TILES", f"VECTOR_FORMAT={vector_format}"],
    )

    assert ds is not None

    lyr = ds.GetLayerByName("Zoom level 2")
    assert lyr is not None

    feat = lyr.GetNextFeature()

    # mvt and json geometries differ in the vertex order and precision
    # let's check the bbox with some tolerance
    if (
        feat.GetGeometryRef().GetEnvelope()
        != pytest.approx((-9.454, -9.190, 53.422, 53.519), abs=0.01)
        or feat.GetField("name") != "Corrib ( Lough )"
    ):
        feat.DumpReadable()
        pytest.fail("did not get expected feature")

    del lyr
    del ds


@pytest.mark.parametrize(
    "api,collection",
    (
        ("MAP", "Collection ne_10m_lakes_europe"),
        ("TILES", "Collection ne_10m_lakes_europe"),
        ("COVERAGE", "SRTM"),
    ),
)
def test_ogr_ogcapi_raster(api, collection):

    ds = gdal.OpenEx(
        "OGCAPI:http://127.0.0.1:%d/fakeogcapi" % gdaltest.webserver_port,
        gdal.OF_RASTER,
        open_options=["CACHE=NO", f"API={api}"],
    )

    assert ds is not None

    sub_ds_uri = [v[0] for v in ds.GetSubDatasets() if collection in v[1]][0]

    del ds

    ds = gdal.OpenEx(
        sub_ds_uri,
        gdal.OF_RASTER,
        open_options=["CACHE=NO", f"API={api}"],
    )

    assert ds is not None

    with TemporaryDirectory() as tmpdir:
        options = gdal.TranslateOptions(
            gdal.ParseCommandLine(
                f"-outsize 100 100 -oo API={api} -projwin -9.5377 53.5421 -9.0557 53.2953"
            )
        )
        out_path = os.path.join(tmpdir, "lough_corrib.png")

        gdal.Translate(out_path, ds, options=options)

        control_image_path = os.path.join(
            BASE_TEST_DATA_PATH, f"expected_map_lough_corrib_{api}.png"
        )

        # When recording also regenerate control images
        if RECORD:
            shutil.copyfile(out_path, control_image_path)

        with open(control_image_path, "rb") as expected:
            with open(out_path, "rb") as out_data:
                assert out_data.read() == expected.read()


@pytest.mark.parametrize(
    "api,of_type",
    (
        ("MAP", gdal.OF_RASTER),
        ("TILES", gdal.OF_RASTER),
        ("COVERAGE", gdal.OF_RASTER),
        ("TILES", gdal.OF_VECTOR),
    ),
)
def test_ogc_api_wrong_collection(api, of_type):

    with pytest.raises(Exception, match="Invalid data collection"):
        gdal.OpenEx(
            f"OGCAPI:http://127.0.0.1:{gdaltest.webserver_port}/fakeogcapi/collections/NOT_EXISTS",
            of_type,
            open_options=["CACHE=NO", f"API={api}"],
        )


@pytest.mark.parametrize(
    "api,of_type",
    (
        ("MAP", gdal.OF_RASTER),
        ("TILES", gdal.OF_RASTER),
        ("COVERAGE", gdal.OF_RASTER),
        ("TILES", gdal.OF_VECTOR),
    ),
)
def test_wrong_url(api, of_type):

    with pytest.raises(Exception, match="File Not Found"):
        gdal.OpenEx(
            f"OGCAPI:http://127.0.0.1:{gdaltest.webserver_port}/NOT_FOUND/",
            of_type,
            open_options=["CACHE=NO", f"API={api}"],
        )


def test_ogc_api_raster_tiles():

    ds = gdal.OpenEx(
        f"OGCAPI:http://127.0.0.1:{gdaltest.webserver_port}/fakeogcapi/collections/HRDEM-RedRiver:DTM:2m",
        gdal.OF_RASTER,
        open_options=["API=TILES", "CACHE=NO", "TILEMATRIXSET=WorldMercatorWGS84Quad"],
    )
    assert ds.RasterCount == 4
    assert ds.RasterXSize == 82734
    assert ds.RasterYSize == 106149
    assert ds.GetGeoTransform() == pytest.approx(
        (
            -10902129.741315002,
            2.388657133911758,
            0.0,
            6479743.648362301,
            0.0,
            -2.388657133911758,
        )
    )
    assert ds.GetRasterBand(1).GetOverviewCount() == 16
    assert ds.GetRasterBand(1).GetOverview(15).Checksum() == 5
    assert ds.GetRasterBand(1).ReadBlock(
        ds.RasterXSize // 2 // 256, ds.RasterYSize // 2 // 256
    )
