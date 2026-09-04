from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from home import views


urlpatterns = [

    path(
        'admin/',
        admin.site.urls
    ),

    path(
        '',
        views.home,
        name='home'
    ),

    path(
        'nostros/',
        views.nostros,
        name='nostros'
    ),
    

    path(
        'ledgers/',
        views.ledgers,
        name='ledgers'
    ),

    path(
        'matching/',
        views.matching,
        name='matching'
    ),

    path(
        'download/matched/',
        views.download_matched,
        name='download_matched'
    ),

    path(
        'download/review/',
        views.download_review,
        name='download_review'
    ),

    path(
        'download/unmatched/',
        views.download_unmatched,
        name='download_unmatched'
    ),
    path(
        'login/',
        auth_views.LoginView.as_view(template_name='home/login.html'),
        name='login'
    ),

    path(
        'logout/',
        auth_views.LogoutView.as_view(next_page='login'),
        name='logout'
    ),

]