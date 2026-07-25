import renderdoc as rd
import rdtest


class D3D11_Action_Visibility_Dispatch(rdtest.TestCase):
    demos_test_name = "D3D11_Simple_Dispatch"

    def check_capture(self):
        actions = []

        def append_actions(action):
            actions.append(action)
            for child in action.children:
                append_actions(child)

        for root in self.controller.GetRootActions():
            append_actions(root)

        dispatches = [
            action
            for action in actions
            if action.flags & rd.ActionFlags.Dispatch
            and not action.flags & rd.ActionFlags.Indirect
            and len(action.children) == 0
        ]
        self.check(len(dispatches) > 0, "Expected a direct D3D11 dispatch action")
        self.check(
            dispatches[0].IsActionVisibilityEligible(),
            "Direct D3D11 dispatch must be Action Visibility eligible",
        )
