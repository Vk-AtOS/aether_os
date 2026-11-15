"""KAN-196: the hardware skeletons say, in their README, that they are TODO skeletons without safety logic."""
from aether_os.phases.p03_scaffolding.generators_helpers import _firmware_c_files, _ros2_py_files


def test_hardware_skeleton_readmes_carry_the_not_production_note():
    for files in (_firmware_c_files("Demo"), _ros2_py_files("Demo")):
        assert "Not production code" in files["README.md"] and "safety logic" in files["README.md"]
        assert any("TODO" in body for name, body in files.items() if name != "README.md")
