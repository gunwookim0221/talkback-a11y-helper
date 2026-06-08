from __future__ import annotations

from tb_runner.plugin_card_discovery import (
    build_known_plugin_index,
    discover_device_cards,
    discover_life_cards_from_xml,
)
from tb_runner.scenario_config import TAB_CONFIGS


def test_device_card_converts_to_discovery_card_with_stable_label():
    nodes = [
        {
            "text": "Audio Pause",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/device_card",
            "className": "android.view.ViewGroup",
            "boundsInScreen": "40,420,1040,760",
            "clickable": True,
            "visibleToUser": True,
        }
    ]

    cards = discover_device_cards(nodes, known_index=build_known_plugin_index(TAB_CONFIGS))

    assert len(cards) == 1
    assert cards[0]["type"] == "device"
    assert cards[0]["label"] == "Audio Pause"
    assert cards[0]["stable_label"] == "Audio"
    assert cards[0]["confidence"] == "high"
    assert cards[0]["source"] == "helper"
    assert cards[0]["resource_id"] == "com.samsung.android.oneconnect:id/device_card"
    assert cards[0]["known"] is True
    assert cards[0]["existing_scenario_id"] == "device_audio_plugin"


def test_device_card_dedupes_by_stable_label():
    nodes = [
        {
            "text": "누수 Dry",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/device_card",
            "className": "android.view.ViewGroup",
            "boundsInScreen": "40,420,1040,760",
            "clickable": True,
        },
        {
            "text": "누수",
            "viewIdResourceName": "com.samsung.android.oneconnect:id/device_card",
            "className": "android.view.ViewGroup",
            "boundsInScreen": "40,800,1040,1140",
            "clickable": True,
        },
    ]

    cards = discover_device_cards(nodes)

    assert len(cards) == 1
    assert cards[0]["stable_label"] == "누수"


def test_life_discovery_filters_chrome_and_dedupes_labels():
    xml = """
    <hierarchy>
      <node text="More options" class="android.widget.Button" resource-id="com.pkg:id/more_menu_button" bounds="[940,20][1040,120]" clickable="true"/>
      <node text="Life" class="android.widget.TextView" resource-id="com.pkg:id/bottomTabLife" bounds="[420,1760][620,1860]"/>
      <node text="" class="android.widget.FrameLayout" resource-id="com.pkg:id/preInstalledServiceCard" bounds="[40,420][1040,760]" clickable="true">
        <node text="Home Care" class="android.widget.TextView" resource-id="com.pkg:id/tvHeaderTitle" bounds="[80,450][500,520]"/>
        <node text="Connect Samsung home appliances" class="android.widget.TextView" bounds="[80,540][900,620]"/>
      </node>
      <node text="" class="android.widget.FrameLayout" resource-id="com.pkg:id/preInstalledServiceCard" bounds="[40,800][1040,1140]" clickable="true">
        <node text="Home Care" class="android.widget.TextView" resource-id="com.pkg:id/tvHeaderTitle" bounds="[80,830][500,900]"/>
      </node>
    </hierarchy>
    """

    cards = discover_life_cards_from_xml(xml, known_index=build_known_plugin_index(TAB_CONFIGS))

    assert [card["label"] for card in cards] == ["Home Care"]
    assert cards[0]["type"] == "life"
    assert cards[0]["confidence"] == "high"
    assert cards[0]["source"] == "xml"
    assert cards[0]["known"] is True
    assert cards[0]["existing_scenario_id"] == "life_home_care_plugin"


def test_life_discovery_excludes_uncertain_status_text_without_card_hint():
    xml = """
    <hierarchy>
      <node text="Connected" class="android.widget.TextView" bounds="[80,450][500,520]"/>
      <node text="Navigate up" class="android.widget.Button" bounds="[20,20][120,120]" clickable="true"/>
    </hierarchy>
    """

    assert discover_life_cards_from_xml(xml) == []


def test_life_discovery_filters_toolbar_profile_location_and_misc_false_positives():
    xml = """
    <hierarchy>
      <node text="" class="android.view.ViewGroup" resource-id="com.samsung.android.oneconnect:id/toolbar_layout" bounds="[0,94][1080,310]">
        <node text="우리 집" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/title" bounds="[180,170][376,257]"/>
        <node text="" class="android.widget.ImageButton" resource-id="com.samsung.android.oneconnect:id/add_menu_button" content-desc="Add" bounds="[810,142][918,286]" clickable="true"/>
        <node text="" class="android.widget.ImageButton" resource-id="com.samsung.android.oneconnect:id/more_menu_button" content-desc="More options" bounds="[918,142][1026,286]" clickable="true"/>
      </node>
      <node text="" class="android.widget.FrameLayout" resource-id="com.pkg:id/preInstalledServiceCard" bounds="[40,420][1040,760]" clickable="true">
        <node text="Family Care" class="android.widget.TextView" resource-id="com.pkg:id/tvHeaderTitle" bounds="[80,450][500,520]"/>
      </node>
      <node text="" class="android.widget.FrameLayout" resource-id="com.pkg:id/preInstalledServiceCard" bounds="[40,800][1040,1140]" clickable="true">
        <node text="Food" class="android.widget.TextView" resource-id="com.pkg:id/tvHeaderTitle" bounds="[80,830][500,900]"/>
      </node>
      <node text="" class="android.widget.FrameLayout" resource-id="com.pkg:id/preInstalledServiceCard" bounds="[40,1180][1040,1520]" clickable="true">
        <node text="Home Care" class="android.widget.TextView" resource-id="com.pkg:id/tvHeaderTitle" bounds="[80,1210][500,1280]"/>
      </node>
      <node text="" class="android.widget.RelativeLayout" resource-id="com.pkg:id/profile_card" bounds="[40,1560][1040,1880]" clickable="true">
        <node text="안 창준 (Me)" class="android.widget.TextView" resource-id="com.pkg:id/profile_name" bounds="[80,1590][500,1660]"/>
        <node text="Active" class="android.widget.TextView" resource-id="com.pkg:id/status_text" bounds="[80,1670][280,1730]"/>
        <node text="Picture" class="android.widget.TextView" resource-id="com.pkg:id/picture_label" bounds="[80,1740][280,1800]"/>
      </node>
      <node text="" class="android.widget.RelativeLayout" resource-id="com.pkg:id/food_card_content" bounds="[40,1900][520,2100]" clickable="true">
        <node text="바코드 스캔" class="android.widget.TextView" resource-id="com.pkg:id/barcode_label" bounds="[80,1940][280,2000]"/>
      </node>
      <node text="0" class="android.widget.TextView" resource-id="com.pkg:id/notifications_badge" bounds="[900,2340][1010,2400]"/>
      <node text="" class="android.widget.Button" resource-id="com.pkg:id/search_button" content-desc="Search" bounds="[920,20][1040,120]" clickable="true"/>
    </hierarchy>
    """

    cards = discover_life_cards_from_xml(xml, known_index=build_known_plugin_index(TAB_CONFIGS))

    assert [card["label"] for card in cards] == ["Family Care", "Food", "Home Care"]


def test_life_discovery_accepts_service_container_structure_with_container_name():
    xml = """
    <hierarchy>
      <node text="" class="android.widget.RelativeLayout" bounds="[42,875][1038,1607]" clickable="true">
        <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/serviceCardBody" bounds="[42,875][1038,1607]">
          <node text="Clothing Care" class="android.widget.LinearLayout" resource-id="com.samsung.android.oneconnect:id/llCard" bounds="[42,875][1038,1607]">
            <node text="" class="android.widget.RelativeLayout" resource-id="com.samsung.android.oneconnect:id/containerNameLayout" bounds="[42,875][1038,1007]">
              <node text="Clothing Care" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/containerName" bounds="[42,875][392,1007]"/>
            </node>
            <node text="To use the clothing and shoe care service, connect your phone to your Samsung appliances." class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/tvHeaderTitle" bounds="[84,1022][996,1199]"/>
          </node>
        </node>
      </node>
    </hierarchy>
    """

    cards = discover_life_cards_from_xml(xml)

    assert [card["label"] for card in cards] == ["Clothing Care"]


def test_life_discovery_finds_find_card_without_using_map_text_as_title():
    xml = """
    <hierarchy>
      <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/map_area" bounds="[40,420][1040,980]" clickable="true">
        <node text="Find" class="android.widget.LinearLayout" resource-id="com.samsung.android.oneconnect:id/fme_title_layout" bounds="[80,450][400,520]"/>
        <node text="Find" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/container_name" bounds="[80,450][300,520]"/>
        <node text="Find, 창준의 S24 Ultra, Last updated: 3 min ago" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/map_area" bounds="[80,560][900,640]"/>
        <node text="" class="android.view.View" resource-id="com.samsung.android.oneconnect:id/fme_map_touch_layer" bounds="[80,650][960,940]" clickable="true"/>
        <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/fme_map_bubble_layout" bounds="[420,680][900,860]" clickable="true">
          <node text="창준의 S24 Ultra" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/container_name" bounds="[450,710][820,770]"/>
          <node text="Living room" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/bubble_title" bounds="[450,770][700,820]"/>
          <node text="3 min ago" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/bubble_time" bounds="[450,820][620,850]"/>
        </node>
      </node>
    </hierarchy>
    """

    cards = discover_life_cards_from_xml(xml, known_index=build_known_plugin_index(TAB_CONFIGS))

    assert [card["label"] for card in cards] == ["Find"]
    assert cards[0]["existing_scenario_id"] == "life_find_plugin"


def test_life_discovery_finds_video_card_without_using_description_as_title():
    xml = """
    <hierarchy>
      <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/title_view" bounds="[40,420][1040,980]" clickable="true">
        <node text="Video" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/title_service_name" bounds="[80,450][400,520]"/>
        <node text="No clips recorded today" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/camera_description" bounds="[80,560][700,640]"/>
      </node>
    </hierarchy>
    """

    cards = discover_life_cards_from_xml(xml, known_index=build_known_plugin_index(TAB_CONFIGS))

    assert [card["label"] for card in cards] == ["Video"]
    assert cards[0]["existing_scenario_id"] == "life_video_plugin"


def test_life_discovery_keeps_sibling_service_cards_while_suppressing_find_internal_items():
    xml = """
    <hierarchy>
      <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/preInstalledServiceCard" bounds="[40,320][1040,640]" clickable="true">
        <node text="Air Care" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/tvHeaderTitle" bounds="[80,360][420,430]"/>
      </node>
      <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/map_area" bounds="[40,680][1040,1240]" clickable="true">
        <node text="Find" class="android.widget.LinearLayout" resource-id="com.samsung.android.oneconnect:id/fme_title_layout" bounds="[80,710][400,780]"/>
        <node text="Find" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/container_name" bounds="[80,710][300,780]"/>
        <node text="MapView" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/map_area" bounds="[760,720][960,770]"/>
        <node text="NAVER" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/map_provider" bounds="[760,780][960,830]"/>
        <node text="" class="android.view.View" resource-id="com.samsung.android.oneconnect:id/fme_map_touch_layer" bounds="[80,810][960,1180]" clickable="true"/>
        <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/fme_map_bubble_layout" bounds="[420,860][900,1040]" clickable="true">
          <node text="창준의 S24 Ultra" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/container_name" bounds="[450,890][820,950]"/>
          <node text="거실" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/bubble_title" bounds="[450,950][700,1000]"/>
          <node text="Last updated: 3 min ago" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/bubble_time" bounds="[450,1000][780,1030]"/>
        </node>
      </node>
      <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/title_view" bounds="[40,1280][1040,1600]" clickable="true">
        <node text="Video" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/title_service_name" bounds="[80,1320][360,1390]"/>
        <node text="No clips recorded today" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/camera_description" bounds="[80,1410][700,1480]"/>
      </node>
      <node text="" class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/serviceCardBody" bounds="[40,1640][1040,2080]" clickable="true">
        <node text="Home Monitor" class="android.widget.TextView" resource-id="com.samsung.android.oneconnect:id/container_name" bounds="[80,1680][460,1750]"/>
      </node>
    </hierarchy>
    """

    cards = discover_life_cards_from_xml(xml, known_index=build_known_plugin_index(TAB_CONFIGS))

    assert [card["label"] for card in cards] == ["Air Care", "Find", "Video", "Home Monitor"]
