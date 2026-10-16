from django.contrib import admin, messages

from .models import Invite, Membership, Team, TeamClaim


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("number", "nickname", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("number", "nickname")
    inlines = [MembershipInline]


@admin.register(TeamClaim)
class TeamClaimAdmin(admin.ModelAdmin):
    list_display = ("team", "user", "full_name", "position", "status", "created_at")
    list_filter = ("status", "position")
    actions = ["approve", "reject"]

    @admin.action(description="Approve selected claims (grants team admin)")
    def approve(self, request, queryset):
        for claim in queryset.filter(status=TeamClaim.Status.PENDING):
            claim.approve(request.user)
        messages.success(request, "Approved.")

    @admin.action(description="Reject selected claims")
    def reject(self, request, queryset):
        for claim in queryset.filter(status=TeamClaim.Status.PENDING):
            claim.reject(request.user)
        messages.success(request, "Rejected.")


admin.site.register(Membership)
admin.site.register(Invite)
