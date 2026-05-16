      *
      * Copybook FOO — customer record layout used by PROGA's file
      * description.
      *
       05  CUST-ID           PIC 9(08).
       05  CUST-NAME         PIC X(30).
       05  CUST-BALANCE      PIC S9(09)V99.
       05  CUST-FLAGS.
           10  CUST-VIP-FLAG    PIC X(01).
           10  CUST-DELQ-FLAG   PIC X(01).
