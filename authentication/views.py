from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.views import View

from django.contrib import messages



class Register(View):
    def get(self, request):
        return render(request, 'authentication/Register.html')

    def post(self, request):
        username = request.POST.get('username')
        password = request.POST.get('password')
        if not (username and password):
            return render(request, 'Register.html', {'error_message': 'Username and password are required.'})

        if User.objects.filter(username=username).exists():
            return render(request, 'Register.html', {'error_message': 'Username already exists. Please choose a different one.'})

        try:
            user = User.objects.create_user(
                username=username, password=password)
        except Exception as e:
            return render(request, 'Register.html', {'error_message': f'Error creating user: {str(e)}'})

        login(request, user)
        messages.success(request, 'Registration successful. Welcome!')

        return redirect('home')


class Login(View):
    def get(self, request):
        return render(request, 'authentication/Login.html')

    def post(self, request):
        username = request.POST.get('username')
        password = request.POST.get('password')

        if not (username and password):
            messages.error(request, 'Registration successful. Welcome!')
            # return render(request, 'Login.html', {'error_message': 'Username and password are required.'})


        try:
            user = User.objects.get(username=username)
            if user.check_password(password):
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('home')
            else:
                messages.error(request, 'Incorrect password. Please try again.')
                return render(request, 'authentication/Login.html', {'error_message': 'Incorrect password.'})
        except User.DoesNotExist:
            messages.error(request, 'User does not exist. Please register first.')
            return render(request, 'authentication/Login.html', {'error_message': 'User does not exist.'})


class Logout(View):

    def get(self, request):
        return redirect('home')

    def post(self, request):
        print('Logout')
        if request.user.is_authenticated:
            logout(request)
            messages.success(request, 'Logout successful.')
        else:
            messages.error(request, 'Logout failed.')
        return redirect('home')