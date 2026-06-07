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
