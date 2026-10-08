import json

_JSON_DATA = '''{
  "kpi": {
    "period": "AUG2026",
    "enquiries": 367,
    "qualified": 361,
    "test_drives": 128.0,
    "bookings": 42,
    "retails": 18,
    "enquiry_to_booking_pct": 11.4,
    "booking_to_retail_pct": 42.9,
    "free_stock": 69,
    "allotted_stock": 20,
    "stock_over_90_days": 20,
    "backorders": 11,
    "bookings_missing_crm_entry": 15,
    "booking_amount_collected": 943001.0,
    "avg_allotment_tat_days": 3.5
  },
  "funnel": {
    "period": "AUG2026",
    "enquiries": 367,
    "qualified": 361,
    "test_drives": 128.0,
    "bookings": 42,
    "retails": 18
  },
  "targets": {
    "leads_target": 450.0,
    "td_target": 300.0,
    "booking_target": 84.0,
    "retail_target": 66.0
  },
  "board": [
    {
      "consultant": "Sreejith K R",
      "team": "PRINCE",
      "primary_channel": "WALKIN",
      "total_leads": 54.0,
      "td_achieved": 18.0,
      "booking_target": 12.0,
      "booking_achieved": 4.0,
      "booking_gap": -8.0,
      "booking_vs_target_pct": 33.3,
      "retail_target": 10.0,
      "retail_achieved": 2.0,
      "retail_vs_target_pct": 20.0,
      "booking_conv_pct": 7.4
    },
    {
      "consultant": "Rishabh J",
      "team": null,
      "primary_channel": "WALKIN",
      "total_leads": 8.0,
      "td_achieved": 4.0,
      "booking_target": 7.0,
      "booking_achieved": 0.0,
      "booking_gap": -7.0,
      "booking_vs_target_pct": 0.0,
      "retail_target": 5.0,
      "retail_achieved": 0.0,
      "retail_vs_target_pct": 0.0,
      "booking_conv_pct": 0.0
    },
    {
      "consultant": "Sanjeev",
      "team": "NETHRA",
      "primary_channel": "TELE",
      "total_leads": 37.0,
      "td_achieved": 17.0,
      "booking_target": 13.0,
      "booking_achieved": 8.0,
      "booking_gap": -5.0,
      "booking_vs_target_pct": 61.5,
      "retail_target": 11.0,
      "retail_achieved": 4.0,
      "retail_vs_target_pct": 36.4,
      "booking_conv_pct": 21.6
    },
    {
      "consultant": "Akhilesh",
      "team": "PRINCE",
      "primary_channel": "WALKIN",
      "total_leads": 60.0,
      "td_achieved": 17.0,
      "booking_target": 12.0,
      "booking_achieved": 7.0,
      "booking_gap": -5.0,
      "booking_vs_target_pct": 58.3,
      "retail_target": 10.0,
      "retail_achieved": 3.0,
      "retail_vs_target_pct": 30.0,
      "booking_conv_pct": 11.7
    },
    {
      "consultant": "Sudhir Poojary",
      "team": "NETHRA",
      "primary_channel": "TELE",
      "total_leads": 39.0,
      "td_achieved": 25.0,
      "booking_target": 12.0,
      "booking_achieved": 7.0,
      "booking_gap": -5.0,
      "booking_vs_target_pct": 58.3,
      "retail_target": 10.0,
      "retail_achieved": 2.0,
      "retail_vs_target_pct": 20.0,
      "booking_conv_pct": 17.9
    },
    {
      "consultant": "Lokesh Reddy K",
      "team": "NETHRA",
      "primary_channel": "TELE",
      "total_leads": 22.0,
      "td_achieved": 16.0,
      "booking_target": 7.0,
      "booking_achieved": 2.0,
      "booking_gap": -5.0,
      "booking_vs_target_pct": 28.6,
      "retail_target": 5.0,
      "retail_achieved": 1.0,
      "retail_vs_target_pct": 20.0,
      "booking_conv_pct": 9.1
    },
    {
      "consultant": "Aditya Kumar",
      "team": "PRINCE",
      "primary_channel": "WALKIN",
      "total_leads": 53.0,
      "td_achieved": 10.0,
      "booking_target": 8.0,
      "booking_achieved": 5.0,
      "booking_gap": -3.0,
      "booking_vs_target_pct": 62.5,
      "retail_target": 6.0,
      "retail_achieved": 2.0,
      "retail_vs_target_pct": 33.3,
      "booking_conv_pct": 9.4
    },
    {
      "consultant": "Abinand P",
      "team": "NETHRA",
      "primary_channel": "TELE",
      "total_leads": 32.0,
      "td_achieved": 2.0,
      "booking_target": 7.0,
      "booking_achieved": 4.0,
      "booking_gap": -3.0,
      "booking_vs_target_pct": 57.1,
      "retail_target": 5.0,
      "retail_achieved": 2.0,
      "retail_vs_target_pct": 40.0,
      "booking_conv_pct": 12.5
    },
    {
      "consultant": "Bhuvaneshwari A",
      "team": "PRINCE",
      "primary_channel": "WALKIN",
      "total_leads": 50.0,
      "td_achieved": 19.0,
      "booking_target": 6.0,
      "booking_achieved": 5.0,
      "booking_gap": -1.0,
      "booking_vs_target_pct": 83.3,
      "retail_target": 4.0,
      "retail_achieved": 2.0,
      "retail_vs_target_pct": 50.0,
      "booking_conv_pct": 10.0
    }
  ],
  "teams": [
    {
      "consultant": "Field Team (Tele & Digital) - Nethra",
      "total_leads": 130.0,
      "booking_target": 39.0,
      "booking_achieved": 21.0,
      "retail_target": 31.0,
      "retail_achieved": 9.0
    },
    {
      "consultant": "S/R Team (Walkin, CRM & W/s) Prince",
      "total_leads": 225.0,
      "booking_target": 45.0,
      "booking_achieved": 21.0,
      "retail_target": 35.0,
      "retail_achieved": 9.0
    }
  ],
  "sources": [
    {
      "source": "CRM",
      "channel": "CRM",
      "is_paid_media": false,
      "leads": 160,
      "qualified": 155,
      "qualified_pct": 96.9
    },
    {
      "source": "TELE",
      "channel": "TELE",
      "is_paid_media": false,
      "leads": 77,
      "qualified": 76,
      "qualified_pct": 98.7
    },
    {
      "source": "WALKIN",
      "channel": "WALKIN",
      "is_paid_media": false,
      "leads": 77,
      "qualified": 77,
      "qualified_pct": 100.0
    },
    {
      "source": "DIGITAL",
      "channel": "DIGITAL",
      "is_paid_media": true,
      "leads": 45,
      "qualified": 45,
      "qualified_pct": 100.0
    },
    {
      "source": "REFERENCE",
      "channel": "REFERRAL",
      "is_paid_media": false,
      "leads": 5,
      "qualified": 5,
      "qualified_pct": 100.0
    },
    {
      "source": "WORKSHOP REFERRAL",
      "channel": "WORKSHOP",
      "is_paid_media": false,
      "leads": 2,
      "qualified": 2,
      "qualified_pct": 100.0
    },
    {
      "source": "SHOWROOM REFERRAL",
      "channel": "REFERRAL",
      "is_paid_media": false,
      "leads": 1,
      "qualified": 1,
      "qualified_pct": 100.0
    }
  ],
  "models": [
    {
      "model": "TAIGUN",
      "free_stock": 38,
      "allotted_stock": 9,
      "total_stock": 47,
      "free_over_90_days": 9,
      "bookings_this_period": 21,
      "backorders_this_period": 6,
      "registered": 7
    },
    {
      "model": "VIRTUS",
      "free_stock": 30,
      "allotted_stock": 11,
      "total_stock": 41,
      "free_over_90_days": 8,
      "bookings_this_period": 20,
      "backorders_this_period": 4,
      "registered": 11
    },
    {
      "model": "TAYRON",
      "free_stock": 1,
      "allotted_stock": 0,
      "total_stock": 1,
      "free_over_90_days": 1,
      "bookings_this_period": 1,
      "backorders_this_period": 1,
      "registered": 0
    }
  ],
  "demand": [
    {
      "model": "VIRTUS",
      "enquiries": 187,
      "bookings": 20,
      "free_stock": 30,
      "enquiry_to_booking_pct": 10.7
    },
    {
      "model": "TAIGUN",
      "enquiries": 169,
      "bookings": 21,
      "free_stock": 38,
      "enquiry_to_booking_pct": 12.4
    },
    {
      "model": "TAYRON",
      "enquiries": 7,
      "bookings": 1,
      "free_stock": 1,
      "enquiry_to_booking_pct": 14.3
    }
  ],
  "ageing": [
    {
      "model": "VIRTUS",
      "ageing_bucket": "91-180",
      "units": 6,
      "avg_days": 139.2,
      "max_days": 164
    },
    {
      "model": "TAIGUN (FL)",
      "ageing_bucket": "91-180",
      "units": 6,
      "avg_days": 113.7,
      "max_days": 131
    },
    {
      "model": "VIRTUS",
      "ageing_bucket": "61-90",
      "units": 9,
      "avg_days": 72.9,
      "max_days": 76
    },
    {
      "model": "TAYRON",
      "ageing_bucket": "91-180",
      "units": 1,
      "avg_days": 97.0,
      "max_days": 97
    },
    {
      "model": "TAIGUN (FL)",
      "ageing_bucket": "61-90",
      "units": 13,
      "avg_days": 70.3,
      "max_days": 87
    },
    {
      "model": "TAIGUN",
      "ageing_bucket": "91-180",
      "units": 1,
      "avg_days": 93.0,
      "max_days": 93
    },
    {
      "model": "TAIGUN (FL)",
      "ageing_bucket": "31-60",
      "units": 11,
      "avg_days": 35.4,
      "max_days": 49
    },
    {
      "model": "VIRTUS",
      "ageing_bucket": "31-60",
      "units": 13,
      "avg_days": 37.8,
      "max_days": 59
    },
    {
      "model": "VIRTUS",
      "ageing_bucket": "0-30",
      "units": 9,
      "avg_days": 11.4,
      "max_days": 24
    },
    {
      "model": "TAIGUN (FL)",
      "ageing_bucket": "0-30",
      "units": 14,
      "avg_days": 14.9,
      "max_days": 24
    },
    {
      "model": "TAIGUN",
      "ageing_bucket": "180+",
      "units": 2,
      "avg_days": 214.0,
      "max_days": 216
    },
    {
      "model": "VIRTUS",
      "ageing_bucket": "180+",
      "units": 4,
      "avg_days": 193.8,
      "max_days": 220
    }
  ],
  "backorders": [
    {
      "booking_id": 66,
      "booking_date": "2025-05-03",
      "days_waiting": 495,
      "customer_name": "PRAVEEN KUMAR K J",
      "mobile": null,
      "consultant": "Sudhir Poojary",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "colour": "Steel Gray Solid",
      "source": "REFERENCE",
      "source_sheet": "Pending Booking",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 67,
      "booking_date": "2025-05-03",
      "days_waiting": 495,
      "customer_name": "KUSHAL",
      "mobile": null,
      "consultant": "Tejas",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Candy White",
      "source": "WALKIN",
      "source_sheet": "Pending Booking",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 70,
      "booking_date": "2025-05-03",
      "days_waiting": 495,
      "customer_name": "CHHANDASRI MISHRA",
      "mobile": null,
      "consultant": "Sudhir Poojary",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "TOPLINE AT",
      "colour": "Carbon Steel Gray Metallic",
      "source": "TELE",
      "source_sheet": "Pending Booking",
      "is_current_period": false,
      "matching_free_units": 1
    },
    {
      "booking_id": 68,
      "booking_date": "2025-05-03",
      "days_waiting": 495,
      "customer_name": "SANJAI S",
      "mobile": null,
      "consultant": "Sreejith K R",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "colour": "Candy White",
      "source": "WALKIN",
      "source_sheet": "Pending Booking",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 65,
      "booking_date": "2025-05-03",
      "days_waiting": 495,
      "customer_name": "MELWIN GLADSON",
      "mobile": null,
      "consultant": "Thameem",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "colour": "Deep Black Pearlescent",
      "source": "TELE",
      "source_sheet": "Pending Booking",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 71,
      "booking_date": "2025-05-05",
      "days_waiting": 493,
      "customer_name": "ARMAAN BAHADUR",
      "mobile": "[REDACTED]",
      "consultant": "Tejas P",
      "model": "GOLF GTI",
      "model_family": "GOLF",
      "variant": "GOLF GTI",
      "colour": "Moonstone Gray / Black",
      "source": "CRM",
      "source_sheet": "Golf & Tiguan R Line Booking",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 64,
      "booking_date": "2026-05-02",
      "days_waiting": 131,
      "customer_name": "PARAMANAND",
      "mobile": null,
      "consultant": "Naveen Y",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "HL AT",
      "colour": "Lava Blue Metallic",
      "source": "TELE",
      "source_sheet": "Pending Booking",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 63,
      "booking_date": "2026-05-02",
      "days_waiting": 131,
      "customer_name": "ROHIT KUMAR",
      "mobile": null,
      "consultant": "Naveen Y",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "CL MT",
      "colour": "Carbon Steel Gray Metallic",
      "source": "TELE",
      "source_sheet": "Pending Booking",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 77,
      "booking_date": "2026-07-18",
      "days_waiting": 54,
      "customer_name": "VEDAVATHI",
      "mobile": null,
      "consultant": "Sreejith K R",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE AT",
      "colour": "Deep Black Pearlescent",
      "source": null,
      "source_sheet": "Booking & Alloted",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 82,
      "booking_date": "2026-07-22",
      "days_waiting": 50,
      "customer_name": "NIRMAL KUMAR LOGANATHAN",
      "mobile": null,
      "consultant": "Sanjeev",
      "model": "TAYRON",
      "model_family": "TAYRON",
      "variant": "TAYRON",
      "colour": "Dolphin Grey",
      "source": null,
      "source_sheet": "Booking & Alloted",
      "is_current_period": false,
      "matching_free_units": 0
    },
    {
      "booking_id": 4,
      "booking_date": "2026-08-08",
      "days_waiting": 33,
      "customer_name": "TUSHAR K BHARATI",
      "mobile": null,
      "consultant": "Lokesh Reddy K",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "CL MT",
      "colour": "Lava Blue Metallic",
      "source": "TELE",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 5,
      "booking_date": "2026-08-09",
      "days_waiting": 32,
      "customer_name": "N ROOPESH REDDY",
      "mobile": null,
      "consultant": "Aditya Kumar",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "HL MT",
      "colour": "Lava Blue Metallic",
      "source": "WALKIN",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 9,
      "booking_date": "2026-08-10",
      "days_waiting": 31,
      "customer_name": "KARTHICK",
      "mobile": null,
      "consultant": "Sreejith K R",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Candy White",
      "source": "WALKIN",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 7,
      "booking_date": "2026-08-10",
      "days_waiting": 31,
      "customer_name": "SACHIN MOHANAN",
      "mobile": null,
      "consultant": "Aditya Kumar",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "HL MT",
      "colour": "Lava Blue Metallic",
      "source": "WALKIN",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 15,
      "booking_date": "2026-08-14",
      "days_waiting": 27,
      "customer_name": "JAYASHREE",
      "mobile": null,
      "consultant": "Akhilesh",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "1.5 MT SPORT",
      "colour": "Wild Cherry Red Metallic",
      "source": "REFERENCE",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 19,
      "booking_date": "2026-08-16",
      "days_waiting": 25,
      "customer_name": "V ARJUN NARESH",
      "mobile": null,
      "consultant": "Sanjeev",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "HL AT",
      "colour": "Wild Cherry Red Metallic",
      "source": "TELE",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 17,
      "booking_date": "2026-08-16",
      "days_waiting": 25,
      "customer_name": "ARJUN SOM",
      "mobile": null,
      "consultant": "Lokesh Reddy K",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG",
      "colour": "Avocado Green Pearlescent",
      "source": "DIGITAL",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 29,
      "booking_date": "2026-08-22",
      "days_waiting": 19,
      "customer_name": "HARISH",
      "mobile": null,
      "consultant": "Sanjeev",
      "model": "TAYRON",
      "model_family": "TAYRON",
      "variant": "TAYRON",
      "colour": "Ultraviolet",
      "source": "TELE",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 35,
      "booking_date": "2026-08-26",
      "days_waiting": 15,
      "customer_name": "VIGNESH",
      "mobile": null,
      "consultant": "Abinand P",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "HL PLUS MT",
      "colour": "Candy White",
      "source": "TELE",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 38,
      "booking_date": "2026-08-29",
      "days_waiting": 12,
      "customer_name": "ABHILASH",
      "mobile": null,
      "consultant": "Bhuvaneshwari A",
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "TOPLINE MT",
      "colour": "Candy White",
      "source": "WALKIN",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    },
    {
      "booking_id": 42,
      "booking_date": "2026-08-30",
      "days_waiting": 11,
      "customer_name": "HARSHITH V",
      "mobile": null,
      "consultant": "Abinand P",
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "HL PLUS MT",
      "colour": "Candy White",
      "source": "DIGITAL",
      "source_sheet": "Current Month Booking",
      "is_current_period": true,
      "matching_free_units": 0
    }
  ],
  "deadline": [
    {
      "chassis_number": "MEXA26CW2TT015532",
      "model": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 216,
      "nadcon_retail_date": "2026-01-31"
    },
    {
      "chassis_number": "MEXC26D23TT031419",
      "model": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 164,
      "nadcon_retail_date": "2026-03-31"
    },
    {
      "chassis_number": "MEXC26D22TT031413",
      "model": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 164,
      "nadcon_retail_date": "2026-03-31"
    },
    {
      "chassis_number": "MEXC26D22TT033162",
      "model": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 140,
      "nadcon_retail_date": "2026-04-30"
    },
    {
      "chassis_number": "MEXD26CW6TT020133",
      "model": "TAIGUN (FL)",
      "variant": "GT LINE AT",
      "colour": "Wild Cherry Red Metallic",
      "stock_aging_days": 129,
      "nadcon_retail_date": "2026-04-30"
    },
    {
      "chassis_number": "MEXC26D28TT029651",
      "model": "VIRTUS",
      "variant": "HL PLUS MT",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 158,
      "nadcon_retail_date": "2026-04-30"
    },
    {
      "chassis_number": "MEXD26CW8TT019775",
      "model": "TAIGUN (FL)",
      "variant": "TOPLINE AT",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 131,
      "nadcon_retail_date": "2026-04-30"
    },
    {
      "chassis_number": "MEXD26CW1TT019567",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG SPORT",
      "colour": "Candy White / Deep Black Pearlescent",
      "stock_aging_days": 131,
      "nadcon_retail_date": "2026-05-31"
    },
    {
      "chassis_number": "MEXD26CW1TT019360",
      "model": "TAIGUN (FL)",
      "variant": "TOPLINE AT",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 105,
      "nadcon_retail_date": "2026-05-31"
    },
    {
      "chassis_number": "MEXD26D25TT036867",
      "model": "VIRTUS",
      "variant": "TOPLINE AT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 116,
      "nadcon_retail_date": "2026-05-31"
    },
    {
      "chassis_number": "MEXF26D26TT042797",
      "model": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 75,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26D27TT039161",
      "model": "VIRTUS",
      "variant": "GT LINE AT",
      "colour": "Wild Cherry Red Metallic",
      "stock_aging_days": 74,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26CW5TT022587",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 73,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26CW3TT024399",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 73,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXD26D2XTT035097",
      "model": "VIRTUS",
      "variant": "HL AT",
      "colour": "Candy White",
      "stock_aging_days": 73,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26CW7TT024955",
      "model": "TAIGUN (FL)",
      "variant": "GT LINE AT",
      "colour": "Deep Black Pearlescent",
      "stock_aging_days": 73,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26CW4TT024783",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 73,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26D21TT039723",
      "model": "VIRTUS",
      "variant": "GT LINE AT",
      "colour": "Candy White",
      "stock_aging_days": 76,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXA26CW6TT016151",
      "model": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 212,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXD26CW3TT021935",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG SPORT",
      "colour": "Wild Cherry Red Metallic / Deep Black Pearlescent",
      "stock_aging_days": 93,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXC26D23TT031923",
      "model": "VIRTUS",
      "variant": "1.5 DSG",
      "colour": "Wild Cherry Red Metallic / Deep Black Pearlescent",
      "stock_aging_days": 93,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXD26CW1TT019939",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG SPORT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 93,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXB26CW3TT017813",
      "model": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 93,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXD26CW0TT019785",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG SPORT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 87,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXD26D21TT034114",
      "model": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "colour": "Wild Cherry Red Metallic / Deep Black Pearlescent",
      "stock_aging_days": 76,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26CW9TT024584",
      "model": "TAIGUN (FL)",
      "variant": "1.5 DSG",
      "colour": "Deep Black Pearlescent",
      "stock_aging_days": 76,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXE26D22TT040332",
      "model": "VIRTUS",
      "variant": "GT LINE AT",
      "colour": "Wild Cherry Red Metallic",
      "stock_aging_days": 75,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXF26D22TT043915",
      "model": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Deep Black Pearlescent",
      "stock_aging_days": 66,
      "nadcon_retail_date": "2026-06-30"
    },
    {
      "chassis_number": "MEXB26D22TT027695",
      "model": "VIRTUS",
      "variant": "TOPLINE AT",
      "colour": "Reflex Silver Metallic",
      "stock_aging_days": 185,
      "nadcon_retail_date": "2026-07-31"
    },
    {
      "chassis_number": "MEXG26D29TT044905",
      "model": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Deep Black Pearlescent",
      "stock_aging_days": 59,
      "nadcon_retail_date": "2026-07-31"
    },
    {
      "chassis_number": "MEXE26D29TT039727",
      "model": "VIRTUS",
      "variant": "GT LINE AT",
      "colour": "Lava Blue Metallic",
      "stock_aging_days": 39,
      "nadcon_retail_date": "2026-07-31"
    },
    {
      "chassis_number": "MEXG26D22TT047788",
      "model": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Reflex Silver Metallic",
      "stock_aging_days": 39,
      "nadcon_retail_date": "2026-07-31"
    },
    {
      "chassis_number": "MEXG26CW1TT029013",
      "model": "TAIGUN (FL)",
      "variant": "HL AT",
      "colour": "Candy White",
      "stock_aging_days": 37,
      "nadcon_retail_date": "2026-07-31"
    },
    {
      "chassis_number": "MEXF26D29TT043409",
      "model": "VIRTUS",
      "variant": "GT LINE MT",
      "colour": "Carbon Steel Gray Metallic",
      "stock_aging_days": 68,
      "nadcon_retail_date": "2026-07-31"
    }
  ],
  "nocrm": [
    {
      "customer_name": "KARTHICK",
      "consultant": "Sreejith K R",
      "model": "VIRTUS",
      "variant": "GT LINE MT",
      "booking_date": "2026-08-10"
    },
    {
      "customer_name": "DEEPAK",
      "consultant": "Abinand P",
      "model": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "booking_date": "2026-08-14"
    },
    {
      "customer_name": "SANKARE",
      "consultant": "Sudhir Poojary",
      "model": "TAIGUN",
      "variant": "TOPLINE AT",
      "booking_date": "2026-08-20"
    },
    {
      "customer_name": "HARISH",
      "consultant": "Sanjeev",
      "model": "TAYRON",
      "variant": "TAYRON",
      "booking_date": "2026-08-22"
    },
    {
      "customer_name": "PRONOJIT SINGH",
      "consultant": "Sudhir Poojary",
      "model": "TAIGUN",
      "variant": "GT LINE AT",
      "booking_date": "2026-08-22"
    },
    {
      "customer_name": "SANJAY A S",
      "consultant": "Akhilesh",
      "model": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "booking_date": "2026-08-23"
    },
    {
      "customer_name": "DEEPTHAJOTHI S",
      "consultant": "Sudhir Poojary",
      "model": "VIRTUS",
      "variant": "GT LINE AT",
      "booking_date": "2026-08-23"
    },
    {
      "customer_name": "VIGNESH",
      "consultant": "Abinand P",
      "model": "VIRTUS",
      "variant": "HL PLUS MT",
      "booking_date": "2026-08-26"
    },
    {
      "customer_name": "FAZAL AHMAD MANSOORI",
      "consultant": "Sudhir Poojary",
      "model": "VIRTUS",
      "variant": "TOPLINE AT",
      "booking_date": "2026-08-27"
    },
    {
      "customer_name": "PREETHAM POOJARY",
      "consultant": "Sanjeev",
      "model": "TAIGUN",
      "variant": "GT LINE AT",
      "booking_date": "2026-08-27"
    },
    {
      "customer_name": "ABHILASH",
      "consultant": "Bhuvaneshwari A",
      "model": "TAIGUN",
      "variant": "TOPLINE MT",
      "booking_date": "2026-08-29"
    },
    {
      "customer_name": "MULBERRY RESIDENCY",
      "consultant": "Sudhir Poojary",
      "model": "VIRTUS",
      "variant": "GT LINE AT",
      "booking_date": "2026-08-30"
    },
    {
      "customer_name": "PARTHIBAN G K",
      "consultant": "Akhilesh",
      "model": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "booking_date": "2026-08-30"
    },
    {
      "customer_name": "TONY CHRISHTOPER DAVID",
      "consultant": "Sanjeev",
      "model": "VIRTUS",
      "variant": "TOPLINE AT",
      "booking_date": "2026-08-30"
    },
    {
      "customer_name": "HARSHITH V",
      "consultant": "Abinand P",
      "model": "VIRTUS",
      "variant": "HL PLUS MT",
      "booking_date": "2026-08-30"
    }
  ],
  "attach": {
    "registrations": 18,
    "financed": 13,
    "insured": 13,
    "extended_warranty": 1,
    "service_value_package": 1,
    "corporate": 6,
    "finance_pct": 72.2,
    "insurance_pct": 72.2
  },
  "dq": [
    {
      "issue": "Bookings not entered in the CRM",
      "detail": "Bookings on the August tab with ZOHO ENTRY = NO. These will not appear in VW-side reporting until they are punched.",
      "affected_rows": "15",
      "severity": "high"
    },
    {
      "issue": "Test drive tab is stale",
      "detail": "The TD tab holds a November 2024 export, not August 2026 activity. Funnel views take test drives from the scorecard instead.",
      "affected_rows": "31",
      "severity": "high"
    },
    {
      "issue": "Stock past its NADCON retail deadline",
      "detail": "Units whose VW retail deadline has already passed while still unsold.",
      "affected_rows": "34",
      "severity": "high"
    },
    {
      "issue": "Registration report stops at accounts",
      "detail": "On the Reg Report tab the columns from FOLDER SENT TO HO rightwards - invoice date, registration date, registration number, VOIW id and delivery date - are blank on every row, so the fulfilment stage has to be read from the status column instead.",
      "affected_rows": "21",
      "severity": "medium"
    },
    {
      "issue": "August lead export is missing consultant and status columns",
      "detail": "The Leads tab exported only date, name, source and model of interest, so per-consultant enquiry counts must come from the scorecard.",
      "affected_rows": "367",
      "severity": "medium"
    },
    {
      "issue": "Comparision tab disagrees with the base tabs",
      "detail": "Comparision reports 350 enquiries / 37 bookings / 20 retails; the underlying tabs hold 367 / 42 / 18.",
      "affected_rows": "3",
      "severity": "medium"
    },
    {
      "issue": "Daily Tracker holds two conflicting target blocks",
      "detail": "The upper block sets a different enquiry target for the same consultant than the lower block. Views read BLOCK_2 (full roster).",
      "affected_rows": "1",
      "severity": "medium"
    }
  ],
  "meta": {
    "source_file": "DSR August 2026.xlsx",
    "file_modified": "2026-09-08T13:14:37.806007",
    "finished_at": "2026-09-10T17:04:44.426712+05:30"
  },
  "period": {
    "label": "SEP2026",
    "period_start": "2026-09-01",
    "period_end": "2026-09-30"
  },
  "commit": [
    {
      "period": "AUG2026",
      "consultant_label": "AKILESH",
      "window_label": "TILL 12TH",
      "committed": 4.0,
      "achieved": 1.0,
      "variance": -3.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "AKILESH",
      "window_label": "13 TO 19",
      "committed": 2.0,
      "achieved": 2.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "AKILESH",
      "window_label": "20 TO 26",
      "committed": 2.0,
      "achieved": 1.0,
      "variance": -1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "ABBAS",
      "window_label": "TILL 12TH",
      "committed": 2.0,
      "achieved": 1.0,
      "variance": -1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "ABBAS",
      "window_label": "13 TO 19",
      "committed": null,
      "achieved": 0.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "RISHAB",
      "window_label": "TILL 12TH",
      "committed": 1.0,
      "achieved": 1.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "RISHAB",
      "window_label": "13 TO 19",
      "committed": 2.0,
      "achieved": 0.0,
      "variance": -2.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "RISHAB",
      "window_label": "20 TO 26",
      "committed": 2.0,
      "achieved": null,
      "variance": -2.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "BHUVANESWARI",
      "window_label": "20 TO 26",
      "committed": null,
      "achieved": 2.0,
      "variance": 2.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SREEJITH",
      "window_label": "TILL 12TH",
      "committed": 0.0,
      "achieved": 1.0,
      "variance": 1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SREEJITH",
      "window_label": "13 TO 19",
      "committed": 3.0,
      "achieved": 3.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SREEJITH",
      "window_label": "20 TO 26",
      "committed": 3.0,
      "achieved": 4.0,
      "variance": 1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "ADITYA",
      "window_label": "TILL 12TH",
      "committed": 0.0,
      "achieved": 0.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "ADITYA",
      "window_label": "13 TO 19",
      "committed": 0.0,
      "achieved": 1.0,
      "variance": 1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "PRINCE",
      "window_label": "TILL 12TH",
      "committed": 7.0,
      "achieved": 4.0,
      "variance": -3.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "PRINCE",
      "window_label": "13 TO 19",
      "committed": 7.0,
      "achieved": 6.0,
      "variance": -1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "PRINCE",
      "window_label": "20 TO 26",
      "committed": 7.0,
      "achieved": 7.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SANJEEV",
      "window_label": "TILL 12TH",
      "committed": 4.0,
      "achieved": 4.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SANJEEV",
      "window_label": "13 TO 19",
      "committed": 2.0,
      "achieved": 1.0,
      "variance": -1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SANJEEV",
      "window_label": "20 TO 26",
      "committed": 2.0,
      "achieved": 3.0,
      "variance": 1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SUDIR",
      "window_label": "TILL 12TH",
      "committed": 3.0,
      "achieved": 3.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SUDIR",
      "window_label": "13 TO 19",
      "committed": 2.0,
      "achieved": 1.0,
      "variance": -1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "SUDIR",
      "window_label": "20 TO 26",
      "committed": 2.0,
      "achieved": 4.0,
      "variance": 2.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "ABHINAND P",
      "window_label": "20 TO 26",
      "committed": 1.0,
      "achieved": 1.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "LOKESH",
      "window_label": "TILL 12TH",
      "committed": 2.0,
      "achieved": 0.0,
      "variance": -2.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "LOKESH",
      "window_label": "13 TO 19",
      "committed": 1.0,
      "achieved": 0.0,
      "variance": -1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "LOKESH",
      "window_label": "20 TO 26",
      "committed": 1.0,
      "achieved": 1.0,
      "variance": 0.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "HANI",
      "window_label": "TILL 12TH",
      "committed": 2.0,
      "achieved": 1.0,
      "variance": -1.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "HANI",
      "window_label": "13 TO 19",
      "committed": 2.0,
      "achieved": 0.0,
      "variance": -2.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "HANI",
      "window_label": "20 TO 26",
      "committed": 2.0,
      "achieved": 4.0,
      "variance": 2.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "NETRA",
      "window_label": "TILL 12TH",
      "committed": 11.0,
      "achieved": 8.0,
      "variance": -3.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "NETRA",
      "window_label": "13 TO 19",
      "committed": 7.0,
      "achieved": 2.0,
      "variance": -5.0
    },
    {
      "period": "AUG2026",
      "consultant_label": "NETRA",
      "window_label": "20 TO 26",
      "committed": 8.0,
      "achieved": 13.0,
      "variance": 5.0
    }
  ],
  "avail": [
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "TOPLINE AT",
      "transmission": "AT",
      "colour": "Lava Blue Metallic",
      "free_units": 3,
      "freshest_days": 14,
      "oldest_days": 131,
      "earliest_retail_deadline": "2026-04-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Lava Blue Metallic",
      "free_units": 3,
      "freshest_days": 31,
      "oldest_days": 39,
      "earliest_retail_deadline": "2026-07-31"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE MT",
      "transmission": "MT",
      "colour": "Deep Black Pearlescent",
      "free_units": 3,
      "freshest_days": 20,
      "oldest_days": 66,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 2,
      "freshest_days": 93,
      "oldest_days": 212,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 2,
      "freshest_days": 73,
      "oldest_days": 73,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Lava Blue Metallic",
      "free_units": 2,
      "freshest_days": 14,
      "oldest_days": 18,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Candy White / Deep Black Pearlescent",
      "free_units": 2,
      "freshest_days": 49,
      "oldest_days": 131,
      "earliest_retail_deadline": "2026-05-31"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Avocado Green Pearlescent / Deep Black Pearlescent",
      "free_units": 2,
      "freshest_days": 31,
      "oldest_days": 63,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 2,
      "freshest_days": 87,
      "oldest_days": 93,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Steel Gray Solid / Deep Black Pearlescent",
      "free_units": 2,
      "freshest_days": 31,
      "oldest_days": 62,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Deep Black Pearlescent",
      "free_units": 2,
      "freshest_days": 14,
      "oldest_days": 73,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Steel Gray Solid",
      "free_units": 2,
      "freshest_days": 14,
      "oldest_days": 63,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Carbon Steel Matte",
      "free_units": 2,
      "freshest_days": 31,
      "oldest_days": 33,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Wild Cherry Red Metallic",
      "free_units": 2,
      "freshest_days": 74,
      "oldest_days": 75,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE MT",
      "transmission": "MT",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 2,
      "freshest_days": 68,
      "oldest_days": 75,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Lava Blue Metallic",
      "free_units": 1,
      "freshest_days": 216,
      "oldest_days": 216,
      "earliest_retail_deadline": "2026-01-31"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Lava Blue Metallic",
      "free_units": 1,
      "freshest_days": 73,
      "oldest_days": 73,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 76,
      "oldest_days": 76,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Carbon Steel Matte",
      "free_units": 1,
      "freshest_days": 39,
      "oldest_days": 39,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Wild Cherry Red Metallic / Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 93,
      "oldest_days": 93,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 14,
      "oldest_days": 14,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Wild Cherry Red Metallic",
      "free_units": 1,
      "freshest_days": 129,
      "oldest_days": 129,
      "earliest_retail_deadline": "2026-04-30"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Lava Blue Metallic",
      "free_units": 1,
      "freshest_days": 14,
      "oldest_days": 14,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Avocado Green Pearlescent",
      "free_units": 1,
      "freshest_days": 41,
      "oldest_days": 41,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "GT LINE MT",
      "transmission": "MT",
      "colour": "Steel Gray Solid",
      "free_units": 1,
      "freshest_days": 73,
      "oldest_days": 73,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "HL AT",
      "transmission": "AT",
      "colour": "Candy White",
      "free_units": 1,
      "freshest_days": 37,
      "oldest_days": 37,
      "earliest_retail_deadline": "2026-07-31"
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "TOPLINE AT",
      "transmission": "AT",
      "colour": "Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 33,
      "oldest_days": 33,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "TOPLINE AT",
      "transmission": "AT",
      "colour": "Candy White",
      "free_units": 1,
      "freshest_days": 18,
      "oldest_days": 18,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "TOPLINE AT",
      "transmission": "AT",
      "colour": "Steel Gray Solid",
      "free_units": 1,
      "freshest_days": 18,
      "oldest_days": 18,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "TOPLINE AT",
      "transmission": "AT",
      "colour": "Avocado Green Pearlescent",
      "free_units": 1,
      "freshest_days": 31,
      "oldest_days": 31,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "TOPLINE MT",
      "transmission": "MT",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 1,
      "freshest_days": 10,
      "oldest_days": 10,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAIGUN (FL)",
      "model_family": "TAIGUN",
      "variant": "TOPLINE MT",
      "transmission": "MT",
      "colour": "Avocado Green Pearlescent",
      "free_units": 1,
      "freshest_days": 18,
      "oldest_days": 18,
      "earliest_retail_deadline": null
    },
    {
      "model": "TAYRON",
      "model_family": "TAYRON",
      "variant": "TAYRON",
      "transmission": null,
      "colour": "Grenadilla Black Metallic",
      "free_units": 1,
      "freshest_days": 97,
      "oldest_days": 97,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 31,
      "oldest_days": 31,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Wild Cherry Red Metallic / Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 93,
      "oldest_days": 93,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Candy White / Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 33,
      "oldest_days": 33,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG",
      "transmission": "DSG",
      "colour": "Lava Blue Metallic",
      "free_units": 1,
      "freshest_days": 31,
      "oldest_days": 31,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 1,
      "freshest_days": 164,
      "oldest_days": 164,
      "earliest_retail_deadline": "2026-03-31"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Carbon Steel Matte",
      "free_units": 1,
      "freshest_days": 33,
      "oldest_days": 33,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Candy White / Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 1,
      "oldest_days": 1,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Lava Blue Metallic",
      "free_units": 1,
      "freshest_days": 164,
      "oldest_days": 164,
      "earliest_retail_deadline": "2026-03-31"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "1.5 DSG SPORT",
      "transmission": "DSG",
      "colour": "Wild Cherry Red Metallic / Deep Black Pearlescent",
      "free_units": 1,
      "freshest_days": 76,
      "oldest_days": 76,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE AT",
      "transmission": "AT",
      "colour": "Candy White",
      "free_units": 1,
      "freshest_days": 76,
      "oldest_days": 76,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE MT",
      "transmission": "MT",
      "colour": "Wild Cherry Red Metallic",
      "free_units": 1,
      "freshest_days": 14,
      "oldest_days": 14,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE MT",
      "transmission": "MT",
      "colour": "Reflex Silver Metallic",
      "free_units": 1,
      "freshest_days": 39,
      "oldest_days": 39,
      "earliest_retail_deadline": "2026-07-31"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "GT LINE MT",
      "transmission": "MT",
      "colour": "Lava Blue Metallic",
      "free_units": 1,
      "freshest_days": 140,
      "oldest_days": 140,
      "earliest_retail_deadline": "2026-04-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "HL AT",
      "transmission": "AT",
      "colour": "Candy White",
      "free_units": 1,
      "freshest_days": 73,
      "oldest_days": 73,
      "earliest_retail_deadline": "2026-06-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "HL PLUS AT",
      "transmission": "AT",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 1,
      "freshest_days": 220,
      "oldest_days": 220,
      "earliest_retail_deadline": null
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "HL PLUS MT",
      "transmission": "MT",
      "colour": "Lava Blue Metallic",
      "free_units": 1,
      "freshest_days": 158,
      "oldest_days": 158,
      "earliest_retail_deadline": "2026-04-30"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "TOPLINE AT",
      "transmission": "AT",
      "colour": "Reflex Silver Metallic",
      "free_units": 1,
      "freshest_days": 185,
      "oldest_days": 185,
      "earliest_retail_deadline": "2026-07-31"
    },
    {
      "model": "VIRTUS",
      "model_family": "VIRTUS",
      "variant": "TOPLINE AT",
      "transmission": "AT",
      "colour": "Carbon Steel Gray Metallic",
      "free_units": 1,
      "freshest_days": 116,
      "oldest_days": 116,
      "earliest_retail_deadline": "2026-05-31"
    }
  ]
}'''
DATA = json.loads(_JSON_DATA)
