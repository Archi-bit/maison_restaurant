from datetime import timedelta
from rest_framework_simplejwt.tokens import RefreshToken



class StaffRefreshToken(RefreshToken):
    @property
    def access_token(self):
        access = super().access_token
        access["exp"] = min(access["exp"], self["exp"])
        return access


class RememberedStaffRefreshToken(StaffRefreshToken):
    lifetime = timedelta(days=30)
