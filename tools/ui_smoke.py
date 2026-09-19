"""Exercise real wx controls in a hidden frame; never start or change NVDA.

Requires host wxPython. NVDA/service APIs are isolated test doubles. This checks
widget APIs and state changes, not actual screen-reader announcements or audio.
"""
from pathlib import Path
import sys
import unittest
import wx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "addon/synthDrivers"))
from test_nvda_adapter import AdapterTests


class Helper:
    def __init__(self, parent, sizer):
        self.parent, self.sizer = parent, sizer

    def addItem(self, item):
        self.sizer.Add(item)
        return item

    def addLabeledControl(self, label, cls, **kwargs):
        self.sizer.Add(wx.StaticText(self.parent, label=label))
        return self.addItem(cls(self.parent, **kwargs))


class RealControls(unittest.TestCase):
    def runTest(self):
        fixture = AdapterTests()
        fixture.setUp()
        frame = None
        try:
            sys.modules["wx"] = wx
            module = fixture.plugin
            module.wx = wx
            module.guiHelper.BoxSizerHelper = Helper
            fixture.client.status = "Connected"
            fixture.client.output_format = "Test format"
            fixture.client.full_xp_volume = False
            fixture.client.busy = False
            frame = wx.Frame(None, title="Legacy bridge hidden qualification")
            class Panel(wx.Panel, module.BridgePanel):
                pass
            panel = Panel(frame)
            sizer = wx.BoxSizer(wx.VERTICAL)
            panel.SetSizer(sizer)
            panel.makeSettings(sizer)
            connection = panel.buttons["onToggleConnection"]
            self.assertEqual(connection.GetLabel(), "&Disconnect")
            self.assertEqual(panel.voice.GetString(0), "Test Mike")
            self.assertFalse(panel.buttons["onStop"].IsEnabled())
            self.assertTrue(panel.buttons["onTest"].IsEnabled())
            fixture.client.connected = False
            panel.onRefresh(None)
            self.assertEqual(connection.GetLabel(), "Cancel &connection")
            fixture.service.client = None
            panel.onRefresh(None)
            self.assertEqual(connection.GetLabel(), "&Connect")
            fixture.service.client = fixture.client
            fixture.client.connected = True
            fixture.client.voice_snapshot.return_value = ({}, {})
            panel.onRefresh(None)
            self.assertEqual(panel.voice.GetSelection(), wx.NOT_FOUND)
            panel.autoReturn.SetValue(True)
            panel.active.SetValue(False)
            panel.onSave()
            self.assertTrue(fixture.settings["autoReturn"])
            fixture.service.disable.assert_called_once()
            print("PASS real wx controls: construction, state labels, empty voice list, test controls, saved recovery setting; frame never shown")
        finally:
            if frame:
                frame.Destroy()
            fixture.doCleanups()


if __name__ == "__main__":
    app = wx.App(False)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([RealControls()]))
    app.ProcessPendingEvents()
    app.Destroy()
    raise SystemExit(0 if result.wasSuccessful() else 1)
