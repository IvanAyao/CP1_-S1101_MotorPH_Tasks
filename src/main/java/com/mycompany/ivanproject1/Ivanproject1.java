/*
 * Click nbfs://nbhost/SystemFileSystem/Templates/Licenses/license-default.txt to change this license
 */

package com.mycompany.ivanproject1;

/**
 *
 * @author PC
 */
public class Ivanproject1 {

    public static void main(String[] args){
// Employee Personal details
String lastName = "Garcia";
String firstName = "Manuel III";
String birthDay = "10/11/1983";
String epNumber = "#10001";
String position = "Chief Executive Officer";
String address = "Valero Carpark Building Valero Street 1227";
String city = "Makati, City";
int phone = 966-860-270;

// Government mandatory contribution
long sss = 4445060573l;
long philhealth = 820126853951l;
long tin = 442605657000l;
long pagIbig = 691295330870l;

//Salary Details

int basic = 90000;
int rice = 1500;
int phoneAllow = 2000;
int clothAllow = 1000;
int gross = 45000;
double hourly = 535.71;

//Arithmetic operator

int a = 15;
int b = 34;

int sum = a + b;
int difference = a - b;
int product = a * b;
int quotient = a / b;

// Comparison operator

int c = 10;
int d = 15;


// logical operators

boolean condition1 = false;
boolean condition2 = true;

String fullName = lastName + ", "+ firstName;
String location = address + " " + city;


System.out.println("Full Name: " + fullName);
System.out.println("Birthday: " + birthDay);
System.out.println("Address: " + location);
System.out.println("arithmetic operator: " + sum);
System.out.println("comparison operator: " + (c!=d));
System.out.println("conditional operator: " + (condition1 && condition2));



}
}
